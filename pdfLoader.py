#-*- coding: utf-8 -*-

# standard imports
import sys, os

# import OGR
from osgeo import ogr, gdal
from pyproj import Proj

# To avoid 'QVariant' is not defined error
from PyQt4.QtCore import *

import re
from math import sqrt, floor
import numpy as np

ogr.UseExceptions()

# 기본 설정값
LAYER_FILTER = re.compile(u"^지도정보_")
MAP_BOX_LAYER = u"지도정보_도곽"
PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_37612058.pdf"


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
        tmpDistLL = sqrt((point[0]-xMin)**2 + (point[1]-yMax)**2)
        tmpDistLR = sqrt((point[0]-xMax)**2 + (point[1]-yMax)**2)
        tmpDistTL = sqrt((point[0]-xMin)**2 + (point[1]-yMin)**2)
        tmpDistTR = sqrt((point[0]-xMax)**2 + (point[1]-yMin)**2)

        if not distLL or distLL > tmpDistLL:
            distLL = tmpDistLL
            pntLL = point
        if not distLR or distLR > tmpDistLR:
            distLR = tmpDistLR
            pntLR = point
        if not distTL or distTL > tmpDistTL:
            distTL = tmpDistTL
            pntTL = point
        if not distTR or distTR > tmpDistTR:
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


def getMapBox(mapNo):
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
def calcTranform(srcP1, srcP2, srcP3, srcP4, tgtP1, tgtP2, tgtP3, tgtP4):
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

    transform = lambda x: unpad(np.dot(pad(x), A))
    return transform


def importPdf(pdfFilePath):
    # get the driver
    srcDriver = ogr.GetDriverByName("PDF")

    # opening the PDF
    try:
        pdf = srcDriver.Open(pdfFilePath, 0)
    except Exception, e:
        print e
        return

    mapNo = os.path.splitext(findMapNo(os.path.basename(pdfFilePath)))[0]
    boxLL, boxLR, boxTL, boxTR = getMapBox(mapNo)
    print(boxLL, boxLR, boxTL, boxTR)

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

    print(tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)

    # use OGR specific exceptions
    # list to store layers'names
    layerInfoList = []

    # parsing layers by index
    # 레이어 ID, 레이어 이름, 객체 수, 지오매트리 유형
    mapBoxLayerId = None
    mapBoxGeometry = None
    mapBoxPoints = None
    pntLL = pntLR = pntTL = pntTR = None
    for iLayer in range(pdf.GetLayerCount()):
        pdfLayer = pdf.GetLayerByIndex(iLayer)
        name = unicode(pdfLayer.GetName().decode('utf-8'))
        if name == MAP_BOX_LAYER:
            mapBoxLayerId = iLayer
        totalFeatureCnt = pdfLayer.GetFeatureCount()
        pointCount = 0
        lineCount = 0
        curveCount = 0
        polygonCount = 0
        for feature in pdfLayer:
            geometry = feature.GetGeometryRef()
            geomType = geometry.GetGeometryType()
            if geomType == ogr.wkbPoint or geomType == ogr.wkbMultiPoint :
                pointCount += 1
            elif geomType == ogr.wkbLineString or geomType == ogr.wkbMultiLineString:
                lineCount += 1
            elif geomType == ogr.wkbPolygon or geomType == ogr.wkbMultiPolygon:
                polygonCount += 1
            else:
                print(u"[Unknown Type] "+ogr.GeometryTypeToName(geomType))

            if mapBoxLayerId and not mapBoxGeometry:
                if geometry.GetPointCount() == 5:
                    if geometry.GetX(0) == geometry.GetX(4) and geometry.GetY(0) == geometry.GetY(4):
                        mapBoxGeometry = geometry
                        mapBoxPoints = geometry.GetPoints()
                        pntLL, pntLR, pntTL, pntTR = findConner(mapBoxPoints)

        if mapBoxLayerId:
            mapBoxLayerId = None

        layerInfoList.append({'id': iLayer, 'name': name, "totalCount": totalFeatureCnt,
                              "pointCount": pointCount, "lineCount": lineCount, "polygonCount": polygonCount})

    print (pntLL, pntLR, pntTL, pntTR)

    transform = calcTranform(pntLL, pntLR, pntTL, pntTR, tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)

    # TEST
    # return

    # clear canvas
    QgsMapLayerRegistry.instance().removeAllMapLayers()
    canvas = iface.mapCanvas()

    crsWkt = QgsCoordinateReferenceSystem(crsId).toWkt()

    # Create QGIS Layer
    for layerInfo in layerInfoList:

        vPointLayer = None
        vLineLayer = None
        vPolygonLayer = None

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
        # 한번 읽은 레이어는 읽음 포인터를 시작점으로 돌려야 다시 읽을 수 있다.
        pdfLayer.ResetReading()
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
            tgtNpList = transform(srcNpArray)

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

    canvas.setExtent(QgsRectangle(tmBoxLL[0], tmBoxLL[1], tmBoxTR[0], tmBoxTR[1]))

    # clean close
    del pdf

    print("COMPLETED!")


importPdf(PDF_FILE_NAME)