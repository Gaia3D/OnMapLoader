#-*- coding: utf-8 -*-

# standard imports
import sys

# import OGR
from osgeo import ogr, gdal

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
    layer = pdf.GetLayerByIndex(iLayer)
    name = layer.GetName()
    totalFeatureCnt = layer.GetFeatureCount()
    pointCount = 0
    lineCount = 0
    curveCount = 0
    polygonCount = 0
    for feature in layer:
        geometry = feature.GetGeometryRef()
        geomType = geometry.GetGeometryType()
        if geomType == ogr.wkbPoint or geomType == ogr.wkbMultiPoint :
            pointCount += 1
        elif geomType == ogr.wkbLineString or geomType == ogr.wkbMultiLineString:
            lineCount += 1
        elif geomType == ogr.wkbPolygon or geomType == ogr.wkbMultiPolygon:
            polygonCount += 1
        else:
            print("[Unknown Type] "+ogr.GeometryTypeToName(geomType))

    layerInfoList.append({'id': iLayer, 'name': name, "totalCount": totalFeatureCnt,
                          "pointCount": pointCount, "lineCount": lineCount, "polygonCount": polygonCount})

# printing
for layerInfo in layerInfoList:
    print("ID: {}, NAME: {}, TotalCount: {}, PointCount: {}, LineCount: {}, PolygonCount: {}".format(
        layerInfo["id"], layerInfo["name"], layerInfo["totalCount"],
        layerInfo["pointCount"], layerInfo["lineCount"], layerInfo["polygonCount"]))

# exit(0)

# create an output datasource in memory
outDriver = ogr.GetDriverByName('MEMORY')
memFile = outDriver.CreateDataSource('memData')

# open the memory datasource with write access
tmp = outDriver.Open('memData', 1)

testLayerId = 33
testLayerName = "PDF Layer"

# copy a layer to memory
pipes_mem = memFile.CopyLayer(pdf.GetLayerByIndex(testLayerId), testLayerName, ['OVERWRITE=YES'])

# the new layer can be directly accessed via the handle pipes_mem or as source.GetLayer('pipes'):
newLayer = memFile.GetLayer(testLayerName)
# for feature in newLayer:
#     feature.SetField('SOMETHING',1)

# clean close
del pdf