#-*- coding: utf-8 -*-

# standard imports
import sys, os

# import OGR
from osgeo import ogr, gdal, osr
from pyproj import Proj, transform

from qgis.core import *

# To avoid 'QVariant' is not defined error
from PyQt4.QtCore import *

import re
import numpy as np
import copy
import struct
import tempfile
import timeit

try:
    import PyPDF2
    from PyPDF2.filters import *
except:
    import pip
    pip.main(['install', "PyPDF2"])
    import PyPDF2
    from PyPDF2.filters import *

from PIL import Image
from io import BytesIO

ogr.UseExceptions()

# 기본 설정값
LAYER_FILTER = re.compile(u"^지도정보_")
MAP_BOX_LAYER = u"지도정보_도곽"
MAP_CLIP_LAYER = u"지도정보_Other"
PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_37612058.pdf"
NUM_FILTER = re.compile('.*_(\d*)')

def findConner(points):
    pntLL = pntLR = pntTL = pntTR = None

    xList = [item[0] for item in points]
    yList = [item[1] for item in points]

    xMin = min(xList)
    yMin = min(yList)
    xMax = max(xList)
    yMax = max(yList)

    distLL = None
    distLR = None
    distTL = None
    distTR = None

    for point in points:
        tmpDistLL = (point[0]-xMin)**2 + (point[1]-yMax)**2
        tmpDistLR = (point[0]-xMax)**2 + (point[1]-yMax)**2
        tmpDistTL = (point[0]-xMin)**2 + (point[1]-yMin)**2
        tmpDistTR = (point[0]-xMax)**2 + (point[1]-yMin)**2

        if distLL is None or distLL > tmpDistLL:
            distLL = tmpDistLL
            pntLL = point
        if distLR is None or distLR > tmpDistLR:
            distLR = tmpDistLR
            pntLR = point
        if distTL is None or distTL > tmpDistTL:
            distTL = tmpDistTL
            pntTL = point
        if distTR is None or distTR > tmpDistTR:
            distTR = tmpDistTR
            pntTR = point

    return pntLL, pntLR, pntTL, pntTR


def findMapNo(fileBase):
    MAP_NO_FILTER = re.compile(u".*온맵_(.*)$")
    res = MAP_NO_FILTER.search(fileBase)
    if res:
        return res.group(1)
    else:
        return None


def mapNoToMapBox(mapNo):
    if not isinstance(mapNo, basestring):
        return None

    if len(mapNo) == 5:
        scale = 50000
    elif len(mapNo) == 8:
        scale = 5000
    else:
        return None

    try:
        iLat = int(mapNo[0:2])
        iLon = int(mapNo[2:3]) + 120
        index50k = int(mapNo[3:5])
        rowIndex50k = (index50k-1)/4
        colIndex50k = (index50k-1)%4
        if scale == 5000:
            index5k = int(mapNo[5:])
            rowIndex5k = (index5k - 1) / 10
            colIndex5k = (index5k - 1) % 10
    except:
        return None

    minLon = float(iLon) + colIndex50k*0.25
    maxLat = float(iLat) + (1-rowIndex50k*0.25)
    if scale == 50000:
        maxLon = minLon + 0.25
        minLat = maxLat - 0.25
    else: #5000
        minLon += colIndex5k * 0.025
        maxLat -= rowIndex5k * 0.025
        maxLon = minLon + 0.025
        minLat = maxLat - 0.025

    pntLL = (minLon, minLat)
    pntLR = (maxLon, minLat)
    pntTL = (minLon, maxLat)
    pntTR = (maxLon, maxLat)

    return pntLL, pntLR, pntTL, pntTR


# REFER: https://stackoverflow.com/questions/20546182/how-to-perform-coordinates-affine-transformation-using-python-part-2
def calcAffineTranform(srcP1, srcP2, srcP3, srcP4, tgtP1, tgtP2, tgtP3, tgtP4):
    primary = np.array([[srcP1[0], srcP1[1]],
                        [srcP2[0], srcP2[1]],
                        [srcP3[0], srcP3[1]],
                        [srcP4[0], srcP4[1]]])

    secondary = np.array([[tgtP1[0], tgtP1[1]],
                        [tgtP2[0], tgtP2[1]],
                        [tgtP3[0], tgtP3[1]],
                        [tgtP4[0], tgtP4[1]]])

    # Pad the data with ones, so that our transformation can do translations too
    n = primary.shape[0]
    pad = lambda x: np.hstack([x, np.ones((x.shape[0], 1))])
    unpad = lambda x: x[:,:-1]
    X = pad(primary)
    Y = pad(secondary)

    # Solve the least squares problem X * A = Y
    # to find our transformation matrix A
    A, res, rank, s = np.linalg.lstsq(X, Y)

    affineTransform = lambda x: unpad(np.dot(pad(x), A))
    return affineTransform, A.T


def getPdfInformation(pdfFilePath):
    # get the driver
    srcDriver = ogr.GetDriverByName("PDF")

    # opening the PDF
    try:
        pdf = srcDriver.Open(pdfFilePath, 0)
    except Exception, e:
        print e
        return

    mapNo = os.path.splitext(findMapNo(os.path.basename(pdfFilePath)))[0]
    boxLL, boxLR, boxTL, boxTR = mapNoToMapBox(mapNo)
    # print(boxLL, boxLR, boxTL, boxTR)

    # 좌표계 판단
    if boxLL[0] < 126.0:
        crsId = 5185
    elif boxLL[0] < 128.0:
        crsId = 5186
    elif boxLL[0] < 130.0:
        crsId = 5187
    else:
        crsId = 5188

    p = Proj(init="epsg:{}".format(crsId))
    tmBoxLL = p(boxLL[0], boxLL[1])
    tmBoxLR = p(boxLR[0], boxLR[1])
    tmBoxTL = p(boxTL[0], boxTL[1])
    tmBoxTR = p(boxTR[0], boxTR[1])

    # print(tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)

    # use OGR specific exceptions
    # list to store layers'names
    layerInfoList = []

    # parsing layers by index
    # 레이어 ID, 레이어 이름, 객체 수, 지오매트리 유형
    mapBoxLayerId = None
    mapClipLayerId = None
    mapBoxGeometry = None
    mapClipGeometry = None
    boxLL = boxLR = boxTL = boxTR = None
    for iLayer in range(pdf.GetLayerCount()):
        pdfLayer = pdf.GetLayerByIndex(iLayer)
        name = unicode(pdfLayer.GetName().decode('utf-8'))

        if name == MAP_BOX_LAYER:
            mapBoxLayerId = iLayer
        if name == MAP_CLIP_LAYER:
            mapClipLayerId = iLayer
        totalFeatureCnt = pdfLayer.GetFeatureCount()
        pointCount = 0
        lineCount = 0
        polygonCount = 0

        for feature in pdfLayer:
            geometry = feature.GetGeometryRef()
            geomType = geometry.GetGeometryType()
            if geomType == ogr.wkbPoint or geomType == ogr.wkbMultiPoint:
                pointCount += 1
            elif geomType == ogr.wkbLineString or geomType == ogr.wkbMultiLineString:
                lineCount += 1
            elif geomType == ogr.wkbPolygon or geomType == ogr.wkbMultiPolygon:
                polygonCount += 1
            else:
                print(u"[Unknown Type] " + ogr.GeometryTypeToName(geomType))

            # 도곽을 찾아 정보 추출
            if mapBoxLayerId and mapBoxGeometry is None:
                if geometry.GetPointCount() == 5:
                    if geometry.GetX(0) == geometry.GetX(4) and geometry.GetY(0) == geometry.GetY(4):
                        mapBoxGeometry = geometry
                        mapBoxPoints = geometry.GetPoints()
                        boxLL, boxLR, boxTL, boxTR = findConner(mapBoxPoints)

            # 영상영역 찾아 정보 추출
            if mapClipLayerId and mapClipGeometry is None:
                if geometry.GetPointCount() == 5:
                    if geometry.GetX(0) == geometry.GetX(4) and geometry.GetY(0) == geometry.GetY(4):
                        mapClipGeometry = geometry
                        mapClipPoints = geometry.GetPoints()
                        imgLL, imgLR, imgTL, imgTR = findConner(mapClipPoints)

        pdfLayer.ResetReading()

        if mapBoxLayerId:
            mapBoxLayerId = None

        layerInfoList.append({'id': iLayer, 'name': name, "totalCount": totalFeatureCnt,
                              "pointCount": pointCount, "lineCount": lineCount, "polygonCount": polygonCount})

    # print (boxLL, boxLR, boxTL, boxTR)

    affineTransform, _ = calcAffineTranform(boxLL, boxLR, boxTL, boxTR, tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)

    srcList = [[imgLL[0],imgLL[1]], [imgLR[0],imgLR[1]], [imgTL[0], imgTL[1]], [imgTR[0], imgTR[1]]]
    srcNpArray = np.array(srcList, dtype=np.float32)
    tgtNpArray = affineTransform(srcNpArray)

    return  pdf, layerInfoList, affineTransform, crsId, mapNo, (tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR), (tgtNpArray[0], tgtNpArray[1], tgtNpArray[2], tgtNpArray[3])


def importPdfVector(pdf, layerInfoList, affineTransform, crsId, mapNo, bbox):
    prvTime = calcTime()

    print ("START importPdfVector")

    # 좌표계 정보 생성
    crs = osr.SpatialReference()
    crs.ImportFromEPSG(crsId)
    crsWkt = crs.ExportToWkt()

    # Create QGIS Layer
    for layerInfo in layerInfoList:
        print(layerInfo["name"])

        vPointLayer = None
        vLineLayer = None
        vPolygonLayer = None

        # TODO: 사용자로 부터 옵션 받게 수정
        # 지도정보_ 로 시작하는 레이어만 임포트
        if not LAYER_FILTER.match(layerInfo["name"]) :
            continue

        # Geometry Type 별 레이어 생성
        if layerInfo["pointCount"] > 0:
            layerName = u"{}_Point".format(layerInfo["name"])
            vPointLayer = QgsVectorLayer("Point?crs={}".format(crsWkt), layerName, "memory")
            vPointLayer.dataProvider().addAttributes([QgsField("GID",  QVariant.Int)])
            vPointLayer.updateFields()
            QgsMapLayerRegistry.instance().addMapLayer(vPointLayer)
        if layerInfo["lineCount"] > 0:
            layerName = u"{}_Line".format(layerInfo["name"])
            vLineLayer = QgsVectorLayer("LineString?crs={}".format(crsWkt), layerName, "memory")
            vLineLayer.dataProvider().addAttributes([QgsField("GID", QVariant.Int)])
            vLineLayer.updateFields()
            QgsMapLayerRegistry.instance().addMapLayer(vLineLayer)
        if layerInfo["polygonCount"] > 0:
            layerName = u"{}_Polygon".format(layerInfo["name"])
            vPolygonLayer = QgsVectorLayer("Polygon?crs={}".format(crsWkt), layerName, "memory")
            vPolygonLayer.dataProvider().addAttributes([QgsField("GID", QVariant.Int)])
            vPolygonLayer.updateFields()
            QgsMapLayerRegistry.instance().addMapLayer(vPolygonLayer)

        pdfLayer = pdf.GetLayerByIndex(layerInfo["id"])
        for ogrFeature in pdfLayer:
            geometry = ogrFeature.GetGeometryRef()
            geomType = geometry.GetGeometryType()
            geomWkb = geometry.ExportToWkb()
            fid = ogrFeature.GetFID()

            qgisFeature = QgsFeature()
            qgisGeom = QgsGeometry()
            qgisGeom.fromWkb(geomWkb)

            # collect vertex
            i = 0
            vertex = qgisGeom.vertexAt(i)
            srcList = []
            while (vertex != QgsPoint(0, 0)):
                srcList.append([vertex.x(), vertex.y()])
                i += 1
                vertex = qgisGeom.vertexAt(i)

            srcNpArray = np.array(srcList)

            # transform all vertex
            tgtNpList = affineTransform(srcNpArray)

            # move vertex
            for i in range(0, len(srcNpArray)):
                qgisGeom.moveVertex(tgtNpList[i,0], tgtNpList[i,1], i)

            qgisFeature.setGeometry(qgisGeom)
            if geomType == ogr.wkbPoint or geomType == ogr.wkbMultiPoint:
                qgisFeature.setAttributes([fid])
                vPointLayer.dataProvider().addFeatures([qgisFeature])
            elif geomType == ogr.wkbLineString or geomType == ogr.wkbMultiLineString:
                qgisFeature.setAttributes([fid])
                vLineLayer.dataProvider().addFeatures([qgisFeature])
            elif geomType == ogr.wkbPolygon or geomType == ogr.wkbMultiPolygon:
                qgisFeature.setAttributes([fid])
                vPolygonLayer.dataProvider().addFeatures([qgisFeature])

        print u"Layer: {} - ".format(layerInfo["name"]),
        prvTime = calcTime(prvTime)

    return crsId, bbox


def importPdfRaster(pdfFilePath, crsId, affineTransform, imgBox):

    root, ext = os.path.splitext(pdfFilePath)
    outputFilePath = root + ".tif"
    _, tempFilePath = tempfile.mkstemp(".tif")

    try:
        pdfObj = PyPDF2.PdfFileReader(open(pdfFilePath, "rb"))
    except RuntimeError, e:
        return

    pageObj = pdfObj.getPage(0)

    artBox = pageObj.artBox

    try:
        xObject = pageObj['/Resources']['/XObject'].getObject()
    except KeyError:
        return

    images = {}

    for obj in xObject:
        if xObject[obj]['/Subtype'] == '/Image':
            name = obj[1:]
            m = NUM_FILTER.search(name)
            try:
                id = int(m.group(1))
            except:
                continue
            size = (xObject[obj]['/Width'], xObject[obj]['/Height'])

            colorSpace = xObject[obj]['/ColorSpace']
            if colorSpace == '/DeviceRGB':
                mode = "RGB"
            elif colorSpace == '/DeviceCMYK':
                mode = "CMYK"
            elif colorSpace[0] == "/Indexed":
                mode = "P"
                colorSpace, base, hival, lookup = [v.getObject() for v in colorSpace]
                palette = lookup.getData()
            elif colorSpace[0] == "/ICCBased":
                mode = "P"
                lookup = colorSpace[1].getObject()
                palette = lookup.getData()
            else:
                continue

            try:
                stream = xObject[obj]
                data = stream._data
                filters = stream.get("/Filter", ())
                if type(filters) is not PyPDF2.generic.ArrayObject:
                    filters = [filters]
                leftFilters = copy.deepcopy(filters)

                if data:
                    for filterType in filters:
                        if filterType == "/FlateDecode" or filterType == "/Fl":
                            data = FlateDecode.decode(data, stream.get("/DecodeParms"))
                            leftFilters.remove(filterType)
                        elif filterType == "/ASCIIHexDecode" or filterType == "/AHx":
                            data = ASCIIHexDecode.decode(data)
                            leftFilters.remove(filterType)
                        elif filterType == "/LZWDecode" or filterType == "/LZW":
                            data = LZWDecode.decode(data, stream.get("/DecodeParms"))
                            leftFilters.remove(filterType)
                        elif filterType == "/ASCII85Decode" or filterType == "/A85":
                            data = ASCII85Decode.decode(data)
                            leftFilters.remove(filterType)
                        elif filterType == "/Crypt":
                            decodeParams = stream.get("/DecodeParams", {})
                            if "/Name" not in decodeParams and "/Type" not in decodeParams:
                                pass
                            else:
                                raise NotImplementedError("/Crypt filter with /Name or /Type not supported yet")
                            leftFilters.remove(filterType)

                    # case of Flat image
                    if len(leftFilters) == 0:
                        img = Image.frombytes(mode, size, data)
                        if mode == "P":
                            img.putpalette(palette)
                        if mode == "CMYK":
                            img = img.convert('RGB')
                        images[id] = img

                    # case of JPEG
                    elif len(leftFilters) == 1 and leftFilters[0] == '/DCTDecode':
                        jpgData = BytesIO(data)
                        img = Image.open(jpgData)
                        if mode == "CMYK":
                            imgData = np.frombuffer(img.tobytes(), dtype='B')
                            invData = np.full(imgData.shape, 255, dtype='B')
                            invData -= imgData
                            img = Image.frombytes(img.mode, img.size, invData.tobytes())
                        images[id] = img
            except:
                pass

    del pdfObj

    # 이미지를 ID 순으로 연결
    keys = images.keys()
    keys.sort()

    mergedWidth = None
    mergedHeight = None
    mergedMode = None
    for key in keys:
        image = images[key]
        width, height = image.size
        if mergedWidth is None:
            mergedWidth, mergedHeight = width, height
            mergedMode = image.mode
            continue

        if width != mergedWidth:
            break

        mergedHeight += height

    mergedImage = Image.new("RGB", (mergedWidth, mergedHeight))
    crrY = 0
    for key in keys:
        image = images[key].transpose(Image.FLIP_TOP_BOTTOM)
        mergedImage.paste(image, (0, crrY))
        crrY += image.height
        del image

    mergedImage.save(tempFilePath)
    del mergedImage

    # 좌표계 정보 생성
    crs = osr.SpatialReference()
    crs.ImportFromEPSG(crsId)
    crs_wkt = crs.ExportToWkt()

    # 매트릭스 계산
    srcList = [
        [0, mergedHeight],
        [mergedWidth, mergedHeight],
        [0, 0],
        [mergedWidth, 0]
    ]
    srcNpArray = np.array(srcList, dtype=np.float32)
    srcList = [
        [0, mergedHeight],
        [mergedWidth, mergedHeight],
        [0, 0],
        [mergedWidth, 0]
    ]
    srcNpArray = np.array(srcList, dtype=np.float32)

    _, matrix = calcAffineTranform(
        srcNpArray[0], srcNpArray[1], srcNpArray[2], srcNpArray[3],
        imgBox[0], imgBox[1], imgBox[2], imgBox[3]
    )

    # GeoTIFF 만들기
    outImage = gdal.Open(tempFilePath)
    driver = gdal.GetDriverByName('GTiff')
    gtiff = driver.CreateCopy(outputFilePath, outImage)
    gtiff.SetProjection(crs_wkt)

    # P1(C): x_origin,
    # P2(A): cos(rotation) * x_pixel_size,
    # P3(D): -sin(rotation) * x_pixel_size,
    # P4(F): y_origin,
    # P5(B): sin(rotation) * y_pixel_size,
    # P6(E): cos(rotation) * y_pixel_size)
    gtiff.SetGeoTransform((matrix[0][2], matrix[0][0], matrix[1][0], matrix[1][2], matrix[0][1], matrix[1][1]))

    del gtiff

    # iface.addRasterLayer(outputFilePath, u"영상")
    root = QgsProject.instance().layerTreeRoot()
    rasterLayer = QgsRasterLayer(outputFilePath, u"영상")
    QgsMapLayerRegistry.instance().addMapLayer(rasterLayer, False)
    root.addLayer(rasterLayer)

    return outputFilePath


def calcTime(prvTime = None):
    if prvTime is None:
        return timeit.default_timer()

    crr = timeit.default_timer()
    print("{}ms".format(int((crr - prvTime)*1000)))

    return crr


def main():

    # clear canvas
    QgsMapLayerRegistry.instance().removeAllMapLayers()

    print("START")
    prvTime = calcTime()

    # PDF에서 레이어와 좌표계 변환 정보 추출
    pdf, layerInfoList, affineTransform, crsId, mapNo, bbox, imgBox = getPdfInformation(PDF_FILE_NAME)
    # TODO: 읽지 못한 상황에 대한 대비
    print "getPdfInformation: ",
    prvTime = calcTime(prvTime)

    crsId, bbox = importPdfVector(pdf, layerInfoList, affineTransform, crsId, mapNo, bbox)
    print "importPdfVector: ",
    prvTime = calcTime(prvTime)

    # clean close
    del pdf

    imgFile = importPdfRaster(PDF_FILE_NAME, crsId, affineTransform, imgBox)
    print "importPdfRaster: ",
    prvTime = calcTime(prvTime)

    # Project 좌표계로 변환하여 화면을 이동해야 한다.
    # TODO: 벡터 레이어가 없는 경우 여기서 오류나는 것 수정
    canvas = iface.mapCanvas()
    mapRenderer = canvas.mapRenderer()
    srs = mapRenderer.destinationCrs()
    mapProj = Proj(init="EPSG:{}".format(crsId))
    projProj = Proj(init=srs.authid())
    minPnt = transform(mapProj, projProj, bbox[0][0], bbox[0][1])
    maxPnt = transform(mapProj, projProj, bbox[3][0], bbox[3][1])
    canvas.setExtent(QgsRectangle(minPnt[0], minPnt[1], maxPnt[0], maxPnt[1]))
    canvas.refresh()

    print("COMPLETED!")


###################
# RUN Main function
if __name__ == '__console__':
    main()

if __name__ == '__main__':
    main()
