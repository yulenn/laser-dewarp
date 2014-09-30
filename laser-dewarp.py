#!/usr/bin/python
# A dewarping tool that rectifies a document based on analysis of lasers.

import os, sys, math, argparse, numpy, scipy, cv2, cv
from PIL import Image, ImageMath, ImageFilter
from numpy import polynomial as P
from scipy import stats, integrate, signal

version = '0.2'
options = None

class Line:
  def __init__(self, point1, point2):
    self.slope = (point2[1] - point1[1])/float(point2[0] - point1[0])
    self.point = point1

  def getY(self, x):
    return (x - self.point[0])*self.slope + self.point[1]

  def getX(self, y):
    return (y - self.point[1])/self.slope + self.point[0]

class Laser:
  def __init__(self, laserImage, yBound):
    self.curve = []
    self.spineIndex = 0
    self.findCurve(laserImage, yBound)

  def findCurve(self, laserImage, yBound):
    self.laserPoints = extractLaserPoints(laserImage, yBound)
    self.curve = extractCurve(self.laserPoints)

  def debugImage(self, laserImage, spine, laserColor, spineColor):
    for x in xrange(0, laserImage.size[0]):
      laserImage.putpixel((x, int(self.curve[x])), laserColor)
    for y in xrange(0, laserImage.size[1]):
      laserImage.putpixel((spine, y), spineColor)

###############################################################################

def findLaserImage(path, thresholdVal):
  def allOrNothing(x):
    if x > thresholdVal:
      return 255
    else:
      return 0
    
  image = Image.open(path)
  (channelR, channelG, channelB) = image.split()

  threshold = ImageMath.eval("convert(a, 'L')",
                                 a=channelR, b=channelG, c=channelB)
  threshold = Image.eval(threshold, allOrNothing)
  threshold = threshold.filter(ImageFilter.MedianFilter(5))
  return threshold

###############################################################################

def extractLaserPoints(image, yBound):
  pixels = image.load()
  # Loop over every column and add the y position of the laser points
  result = []
  for x in xrange(image.size[0]):
    column = []
    # Find all laser pixels in this column
    for y in xrange(yBound[0], yBound[1]):
      if pixels[x, y] > 200:
        column.append(y)
    result.append(column)
  return result

def extractCurve(points):
  curve = []
  lastPoint, lastIndex = findNextPoint(0, points, 0)
  for x in xrange(0, len(points)):
    nextPoint, nextIndex = findNextPoint(x, points, lastPoint)
    # If there are no remaining data points, just use the last data
    # point
    if nextIndex == -1 or nextIndex == lastIndex:
      curve.append(lastPoint)
    # Interpolate between the last data point and the next one. In
    # the degenerate case where nextIndex == x, this just results in
    # nextPoint.
    else:
#      totalWeight = abs(x - lastIndex) + abs(x - nextIndex)
#      last = abs(x - nextIndex) * lastPoint
#      next = abs(x - lastIndex) * nextPoint
#      curve.append((last + next) / float(totalWeight))
      curve.append(lastPoint)
    lastPoint = nextPoint
    lastIndex = nextIndex
  return curve

def findNextPoint(start, points, last):
  resultPoint = last
  resultIndex = -1
  for i in xrange(start, len(points)):
    if len(points[i]) > 0:
      resultPoint = float(points[i][-1] + points[i][0]) / 2
      resultIndex = i
      break
  return (resultPoint, resultIndex)

def extractLasers(image):
  top = Laser(image, (0, image.size[1] / 2))
  bottom = Laser(image, (image.size[1] / 2, image.size[1]))
  return [top, bottom]

def extractSpines(curves):
  result = []
  start = int(len(curves[0].curve)/3)
  end = 2*start
  if options.frame == 'single':
    if options.side == 'odd' or options.side == 'right':
      end = start
      start = 0
    elif options.side == 'even' or options.side == 'left':
      start = end
      end = int(len(curves[0].curve))
  top = findPeaks(curves[0].curve, start=start, end=end,
                  offsetX=20, offsetY=-5, compare=isGreater)
  bottom = findPeaks(curves[1].curve, start=start, end=end,
                     offsetX=20, offsetY=5, compare=isLess)
  if len(top) >= 1 and len(bottom) >= 1:
    result = [top[int(len(top)/2)], bottom[int(len(bottom)/2)]]
  else:
    print 'Could not extract spines.'
    print 'Top: ', top
    print 'Bottom: ', bottom
  return result

def extractEdges(curves):
  start = int(len(curves[0].curve)/3)
  end = 1
  increment = -1
  deltaBack = 16
  deltaForward = 0
  if options.side == 'odd' or options.side == 'right':
    start = 2*start
    end = len(curves[0].curve) - 1
    increment = 1
    deltaBack = 0
    deltaForward = 16
  topPrime = getDerivative(curves[0].curve, deltaBack, deltaForward)
  top = findPeaks(topPrime, start=start, end=end,
                  increment=increment, offsetX=3, offsetY=0, compare=isGreater)
  bottomPrime = getDerivative(curves[1].curve, deltaBack, deltaForward)
  bottom = findPeaks(bottomPrime, start=start, end=end,
                     increment=increment, offsetX=3, offsetY=0, compare=isLess)
  result = [findEdge(topPrime, top, end),
            findEdge(bottomPrime, bottom, end)]
  return result

def findEdge(points, candidates, default):
  result = default
  clipped, low, high = stats.sigmaclip(points, low=3.0, high=3.0)
  for candidate in candidates:
    if points[candidate] < low or points[candidate] > high:
      result = candidate
      break
  return result

def isGreater(a, b):
  return a >= b

def isLess(a, b):
  return a <= b

def getDerivative(curve, deltaBack, deltaForward):
  result = []
  for i in xrange(0, len(curve)):
    deltaLeft = max(i - deltaBack, 0)
    deltaRight = min(i + deltaForward, len(curve) - 1)
    result.append(float(curve[deltaRight] - curve[deltaLeft])/(deltaBack + deltaForward))
  return result

def findPeaks(points, start=0, end=0, increment=1,
              offsetX=1, offsetY=0, compare=isLess):
  results = []
  i = start
  while i != end:
    left = constrainPoint(i - offsetX, start, end)
    right = constrainPoint(i + offsetX, start, end)
    if (isPeak(points, candidate=i, end=left,
               increment=-1, compare=compare) and
        isPeak(points, candidate=i, end=right,
               increment=1, compare=compare) and
        taller(points[i], test=points[left],
               offset=offsetY, compare=compare) and
        taller(points[i], test=points[right],
               offset=offsetY, compare=compare)):
      results.append(i)
    i += increment
  return results

def constrainPoint(pos, start, end):
  result = pos
  if start < end:
    if pos < start:
      result = start
    if pos > end - 1:
      result = end - 1
  else:
    if pos > start:
      result = start
    if pos < end + 1:
      result = end + 1
  return result

def isPeak(points, candidate=0, end=1, increment=1, compare=isLess):
  result = True
  i = candidate
  while i != end:
    if not compare(points[candidate], points[i]):
      result = False
    i += increment
  return result

def taller(candidate, test=0, offset=0, compare=isLess):
  return compare(candidate + offset, test)

# ima is max (for thickest point) or min (for thinnest)
def findExtreme(points, start, end, increment, ima):
  extremeIndex = start
  if start != end and start >= 0:
    extreme = (points[start])
    i = start
    while i != end:
      if ima(extreme, (points[i])) != extreme:
        extreme = ima(extreme, (points[i]))
        extremeIndex = i
      i += increment
  return extremeIndex

###############################################################################

def outputArcDewarp(imagePath, laserLines, spines, edges, laserImage):
  source = cv2.imread(imagePath)#Image.open(imagePath)
  if options.side == 'odd' or options.side == 'right':
    image = arcWarp(source, laserLines[0].curve, laserLines[1].curve,
                    spines[0], edges[0],
                    spines[1], edges[1], laserImage)
    cv2.imwrite(options.output_path, image)
#    image.save(options.output_path)
  elif options.side == 'even' or options.side == 'left':
    image = arcWarp(source, laserLines[0].curve, laserLines[1].curve,
                    edges[0], spines[0],
                    edges[1], spines[1], laserImage)
    cv2.imwrite(options.output_path, image)
#    image.save(options.output_path)
  else:
    print 'Error: The page must be either even or odd'
    
###############################################################################

# Based on http://users.iit.demokritos.gr/~bgat/3337a209.pdf
def arcWarp(source, inAB, inDC, A, B, D, C, laserImage):
  print A, B, D, C
  AB = calculatePoly(inAB, A, B)
  DC = calculatePoly(inDC, D, C)
  if options.debug:
    makePolyImage(laserImage, AB, DC, A, B, D, C).save('tmp/poly.png')
  ABarc = calculateArc(AB, A, B, source.shape[1])
  DCarc = calculateArc(DC, D, C, source.shape[1])
  width = max(ABarc[B], DCarc[C])
  height = min(distance([A, AB(A)], [D, DC(D)]),
               distance([B, AB(B)], [C, DC(C)]))
  startY = AB(A)
  finalWidth = int(math.ceil(width))

  map_x = numpy.asarray(cv.CreateMat(source.shape[0], finalWidth, cv.CV_32FC1)[:,:])
  map_y = numpy.asarray(cv.CreateMat(source.shape[0], finalWidth, cv.CV_32FC1)[:,:])

  topX = A
  bottomX = D
  for destX in xrange(A, finalWidth + A):
    Earc = (destX - A) / float(width) * ABarc[B]
    while topX < B and ABarc[topX] < Earc:
      topX += 1
    E = [topX, AB(topX)]
    while bottomX < C and DCarc[bottomX]/DCarc[C] < Earc/ABarc[B]:
      bottomX += 1
    G = [bottomX, DC(bottomX)]
    sourceAngle = math.atan2(G[1] - E[1], G[0] - E[0])
    cosAngle = math.cos(sourceAngle)
    sinAngle = math.sin(sourceAngle)
    distanceEG = distance(E, G) / height
    for destY in xrange(0, source.shape[0]):
      sourceDist = (destY - startY) * distanceEG
      map_x[destY, int(destX - A)] = E[0] + sourceDist * cosAngle
      map_y[destY, int(destX - A)] = E[1] + sourceDist * sinAngle
  return cv2.remap(source, map_x, map_y, cv2.INTER_LINEAR)

def calculatePoly(curve, left, right):
  binCount = (right - left)/50
  binned = stats.binned_statistic(xrange(0, right - left), curve[left:right],
                                  statistic='mean', bins=binCount)
  ybins = binned[0]
  xbins = binned[1][:-1]
  for i in xrange(len(xbins)):
    xbins[i] = xbins[i] + (right-left)/(binCount*2) + left
  base = P.polynomial.polyfit(xbins, ybins, 7)
  basePoly = P.polynomial.Polynomial(base)
  return basePoly

def makePolyImage(source, top, bottom, A, B, D, C):
  result = Image.new('RGB', source.size)
  pixels = result.load()
  result.paste(source, (0, 0, source.size[0], source.size[1]))
  for i in xrange(A, B):
    pixels[i, int(top(i))] = (255, 0, 0)
  for i in xrange(D, C):
    pixels[i, int(bottom(i))] = (0, 255, 0)
  return result

def calculateArc(base, left, right, sourceWidth):
  adjustedheight = P.polynomial.polymul([options.height_factor], base.coef)
  prime = P.polynomial.polyder(adjustedheight)
  squared = P.polynomial.polymul(prime, prime)
  poly = P.polynomial.Polynomial(P.polynomial.polyadd([1], squared))
  def intF(x):
#    print x, poly(x)
    return math.sqrt(poly(x))

  integralSum = 0
  arcCurve = []
  for x in xrange(0, left):
    arcCurve.append(0)
  for x in xrange(left, right):
    integralSum = integrate.romberg(intF, left, x, divmax=20)
    arcCurve.append(integralSum)
  for x in xrange(right, sourceWidth):
    arcCurve.append(integralSum)
  return arcCurve

def distance(a, b):
  return math.sqrt((a[0]-b[0])*(a[0]-b[0]) +
                   (a[1]-b[1])*(a[1]-b[1]))

def roundSource(x, y, source, size):
  result = (255, 255, 255)
  intX = int(round(x))
  intY = int(round(y))
  if intX >= 0 and intY >= 0 and intX < size[0] and intY < size[1]:
    result = source[intX, intY]
  return result

def sampleSource(x, y, source, size):
  if x > 0 and y > 0 and x < size[0] - 1 and y < size[1] - 1:
    intX = int(x)
    intY = int(y)
    fracX = x - intX
    fracY = y - intY
    fracXY = fracX * fracY
    a = source[intX+1, intY+1]
    wa = fracXY
    b = source[intX+1, intY]
    wb = fracX - fracXY
    c = source[intX, intY+1]
    wc = fracY - fracXY
    d = source[intX, intY]
    wd = 1 - fracX - fracY + fracXY
    return (int(a[0]*wa + b[0]*wb + c[0]*wc + d[0]*wd),
            int(a[1]*wa + b[1]*wb + c[1]*wc + d[1]*wd),
            int(a[2]*wa + b[2]*wb + c[2]*wc + d[2]*wd))
  elif x >= 0 and y >= 0 and x < size[0] and y < size[1]:
    return source[x, y][0]
  else:
    return (255, 255, 255)

###############################################################################

def makeProcessImage(source, curves, spines, edges):
  result = Image.new('RGB', source.size)
  result.paste(source, (0, 0, source.size[0], source.size[1]))
  pixels = result.load()
  for i in xrange(0, source.size[0]):
    for curve in curves:
      pixels[i, int(curve[i])] = (255, 0, 0)
  for i in xrange(0, source.size[1]):
    for x in spines:
      pixels[int(x), i] = (0, 255, 255)
    for x in edges:
      pixels[int(x), i] = (0, 255, 0)
  return result

###############################################################################

def parseArgs():
  global options
  parser = argparse.ArgumentParser(
    description='A program for dewarping images based on laser measurements taken during scanning.')
  parser.add_argument('--version', dest='version', default=False,
                      action='store_const', const=True,
                      help='Get version information')
  parser.add_argument('--debug', dest='debug', default=False,
                      action='store_const', const=True,
                      help='Print extra debugging information and output pictures to ./tmp while processing (make sure this directory exists).')
  parser.add_argument('--image', dest='image_path', default='image.jpg',
                      help='An image of a document to dewarp')
  parser.add_argument('--laser', dest='laser_path', default='laser.jpg',
                      help='A picture with lasers on and lights out taken of the same page as the image.')
  parser.add_argument('--output', dest='output_path', default='output.png',
                      help='Destination path for dewarped image')
  parser.add_argument('--page', dest='side', default='odd',
                      help='Which side of the spine the page to dewarp is at. Can be either "odd" (equivalent to "right") or "even" (equivalent to "left")')
  parser.add_argument('--frame', dest='frame', default='single',
                      help='The number of pages in the camera shot. Either "single" if the camera is centered on just one page or "double" if the camera is centered on the spine')
  parser.add_argument('--laser-threshold', dest='laser_threshold',
                      type=int, default=40,
                      help='A threshold (0-255) for lasers when calculating warp. High means less reflected laser light will be counted.')
  parser.add_argument('--height-factor', dest='height_factor',
                      type=float, default=1.0,
                      help='The curve of the lasers will be multiplied by this factor to estimate height. The closer the lasers are to the center of the picture, the higher this number should be. When this number is too low, text will be foreshortened near the spine and when it is too high, the text will be elongated. It should normally be between 1.0 and 5.0.'),
  options = parser.parse_args()
  if options.version:
    print 'laser-dewarp.py: Version ' + version
    exit(0)

###############################################################################

def main():
  parseArgs()

  laserImage = findLaserImage(options.laser_path, options.laser_threshold)
  if options.debug:
    laserImage.save('tmp/laser.png')
  laserLines = extractLasers(laserImage)
  spines = extractSpines(laserLines)
  edges = extractEdges(laserLines)

  if options.debug:
    makeProcessImage(laserImage, [laserLines[0].curve, laserLines[1].curve],
                     spines, edges).save('tmp/process.png')
  
  first = getDerivative(laserLines[0].curve, 0, 16)
  second = first
  for i in xrange(0, len(second)):
    second[i] = 500 - second[i]*100
  makeProcessImage(laserImage, [laserLines[0].curve, second],
                   spines, edges).save('tmp/second.png')

  outputArcDewarp(options.image_path, laserLines, spines, edges, laserImage)

#import cProfile
#cProfile.run('main()')
if __name__ == '__main__':
  main()

