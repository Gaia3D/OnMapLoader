#-*- coding: utf-8 -*-

# standard imports
import sys

# import OGR
from osgeo import ogr

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
for iLayer in range(pdf.GetLayerCount()):
    layer = pdf.GetLayerByIndex(iLayer)
    layerInfoList.append({'id': iLayer, 'name': layer.GetName()})

# sorting
layerInfoList.sort()

# printing
for layerInfo in layerInfoList:
    print("ID: {}, NAME: {}".format(layerInfo["id"], layerInfo["name"]))

# exit(0)

# create an output datasource in memory
outDriver = ogr.GetDriverByName('MEMORY')
memFile = outDriver.CreateDataSource('memData')

# open the memory datasource with write access
tmp = outDriver.Open('memData', 1)

# 33 지도정보_건물_건물 8884 LineString
# 32 지도정보_건물_건물명 1 Point
# 32 지도정보_건물_건물명 84 LineString
# 32 지도정보_건물_건물명 476 Polygon
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