#-*- coding: utf-8 -*-

# standard imports
import sys

# import OGR
from osgeo import ogr, gdal

# To avoid 'QVariant' is not defined error
from PyQt4.QtCore import *

import re

#
LAYER_FILTER = re.compile(u"^지도정보_")
MAP_BOX_LAYER = u"지도정보_도곽"

# 캔버스 초기화
QgsMapLayerRegistry.instance().removeAllMapLayers()
canvas = iface.mapCanvas()

# use OGR specific exceptions
ogr.UseExceptions()

# get the driver
srcDriver = ogr.GetDriverByName("PDF")

# opening the PDF
try:
    pdf = srcDriver.Open("/Temp/map.pdf", 0)
except Exception, e:
    print e
    sys.exit()

# list to store layers'names
layerInfoList = []

# parsing layers by index
# 레이어 ID, 레이어 이름, 객체 수, 지오매트리 유형
for iLayer in range(pdf.GetLayerCount()):
    pdfLayer = pdf.GetLayerByIndex(iLayer)
    name = unicode(pdfLayer.GetName().decode('utf-8'))
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

    layerInfoList.append({'id': iLayer, 'name': name, "totalCount": totalFeatureCnt,
                          "pointCount": pointCount, "lineCount": lineCount, "polygonCount": polygonCount})

crsWkt = QgsCoordinateReferenceSystem(crsId).toWkt()
crsId = 5179

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

if vPointLayer:
    canvas.setExtent(vPointLayer.extent())
elif vLineLayer:
    canvas.setExtent(vLineLayer.extent())
elif vPolygonLayer:
    canvas.setExtent(vPolygonLayer.extent())

# clean close
del pdf


print("COMPLETED!")