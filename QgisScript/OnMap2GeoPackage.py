# -*- coding: utf-8 -*-

# standard imports
import sys, os

# import OGR
from osgeo import ogr, gdal, osr

from qgis.core import *
try:
    iface
except:
    import qgis.gui
    iface = qgis.gui.QgisInterface


# To avoid 'QVariant' is not defined error
from PyQt4.QtCore import *
from PyQt4.QtGui import QFileDialog

import re
import numpy as np
import copy
import struct
import tempfile
import timeit
import math
import threading, time

import PyPDF2
from PyPDF2.filters import *
from PyPDF2.pdf import *

from PIL import Image
from io import BytesIO

ogr.UseExceptions()

# 기본 설정값
LAYER_FILTER = re.compile(u"^지도정보_")
MAP_BOX_LAYER = u"지도정보_도곽"
MAP_CLIP_LAYER = u"지도정보_Other"
PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_37612068.pdf"
# PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_358124.pdf"
# PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_376124.pdf"
# PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_37612.pdf"
# PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_NJ52-7.pdf"
NUM_FILTER = re.compile('.*_(\d*)')
SKIP_IMAGE_WIDTH = 2000


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
        tmpDistLL = (point[0] - xMin) ** 2 + (point[1] - yMax) ** 2
        tmpDistLR = (point[0] - xMax) ** 2 + (point[1] - yMax) ** 2
        tmpDistTL = (point[0] - xMin) ** 2 + (point[1] - yMin) ** 2
        tmpDistTR = (point[0] - xMax) ** 2 + (point[1] - yMin) ** 2

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
        return os.path.splitext(res.group(1))[0]
    else:
        return None


def mapNoToMapBox(mapNo):
    if not isinstance(mapNo, basestring):
        return None

    if mapNo[:2].upper() == "NJ" or mapNo[:2].upper() == "NI":
        scale = 250000
    elif len(mapNo) == 5:
        scale = 50000
    elif len(mapNo) == 6:
        scale = 25000
    elif len(mapNo) == 8:
        scale = 5000
    else:
        return None

    if scale == 250000:
        message(u"죄송합니다.25만 도엽은 지원되지 않습니다.")
        return None

        try:
            keyLat = mapNo[:2]
            keyLon = mapNo[2:5]
            subIndex = int(mapNo[5:])

            if keyLat == "NJ":
                maxLat = 39.0
            elif keyLat == "NI":
                maxLat = 36.0
            else:
                return None

            if keyLon == "52-":
                minLon = 126.0
            elif keyLon == "51-":
                minLon = 120.0
            else:
                return None

            rowIndex = (subIndex - 1) / 3
            colIndex = (subIndex - 1) % 3

            minLon += colIndex * 2.0
            maxLat -= rowIndex * 1.0
            maxLon = minLon + 0.125
            minLat = maxLat - 0.125

        except:
            return None

    else:
        try:
            iLat = int(mapNo[0:2])
            iLon = int(mapNo[2:3]) + 120
            index50k = int(mapNo[3:5])
            rowIndex50k = (index50k - 1) / 4
            colIndex50k = (index50k - 1) % 4
            if scale == 25000:
                index25k = int(mapNo[5:])
                rowIndex25k = (index25k - 1) / 2
                colIndex25k = (index25k - 1) % 2
            elif scale == 5000:
                index5k = int(mapNo[5:])
                rowIndex5k = (index5k - 1) / 10
                colIndex5k = (index5k - 1) % 10
        except:
            return None

        minLon = float(iLon) + colIndex50k * 0.25
        maxLat = float(iLat) + (1 - rowIndex50k * 0.25)
        if scale == 50000:
            maxLon = minLon + 0.25
            minLat = maxLat - 0.25
        elif scale == 25000:
            minLon += colIndex25k * 0.125
            maxLat -= rowIndex25k * 0.125
            maxLon = minLon + 0.125
            minLat = maxLat - 0.125
        else:  # 5000
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
    unpad = lambda x: x[:, :-1]
    X = pad(primary)
    Y = pad(secondary)

    # Solve the least squares problem X * A = Y
    # to find our transformation matrix A
    A, res, rank, s = np.linalg.lstsq(X, Y)

    affineTransform = lambda x: unpad(np.dot(pad(x), A))
    return affineTransform, A.T


def getPdfInformation_test(pdfFilePath):
    pdf = PyPDF2.PdfFileReader(pdfFilePath)
    page = pdf.getPage(0)
    content = page["/Contents"].getObject()
    if not isinstance(content, ContentStream):
        content = ContentStream(content, pdf)
    for operands, operator in content.operations:
        print operator
        if operator != "BDC":
            continue


def threadOpenPdf(pdfFilePath):
    srcDriver = ogr.GetDriverByName("PDF")
    pdf = srcDriver.Open(pdfFilePath, 0)
    return pdf


def getPdfInformation(pdfFilePath):
    message(u"PDF 파일에서 정보추출 시작...")
    # mapNo = os.path.splitext(findMapNo(os.path.basename(pdfFilePath)))[0]
    mapNo = findMapNo(os.path.basename(pdfFilePath))
    if mapNo is None:
        return

    try:
        boxLL, boxLR, boxTL, boxTR = mapNoToMapBox(mapNo)
    except:
        message(u"해석할 수 없는 도엽명이어서 중단됩니다.")
        return

    # opening the PDF
    crr = calcTime()
    print "PDF Open: ",
    try:
        srcDriver = ogr.GetDriverByName("PDF")
        pdf = srcDriver.Open(pdfFilePath, 0)

        # gPdf = None
        # trPdfOpen = threading.Thread(target=threadOpenPdf, args=(pdfFilePath,))
        # trPdfOpen.daemon = True
        # trPdfOpen.start()
        #
        # while not gPdf:
        #     time.sleep(1)
        #     print ".",
        #
        # pdf = gPdf

    except Exception, e:
        print e
        return
    crr = calcTime(crr)

    # 좌표계 판단
    if boxLL[0] < 126.0:
        crsId = 5185
    elif boxLL[0] < 128.0:
        crsId = 5186
    elif boxLL[0] < 130.0:
        crsId = 5187
    else:
        crsId = 5188

    fromCrs = osr.SpatialReference()
    fromCrs.ImportFromEPSG(4326)
    toCrs = osr.SpatialReference()
    toCrs.ImportFromEPSG(crsId)
    p = osr.CoordinateTransformation(fromCrs, toCrs)
    tmBoxLL = p.TransformPoint(boxLL[0], boxLL[1])
    tmBoxLR = p.TransformPoint(boxLR[0], boxLR[1])
    tmBoxTL = p.TransformPoint(boxTL[0], boxTL[1])
    tmBoxTR = p.TransformPoint(boxTR[0], boxTR[1])

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
        print(name)

        if name.find(MAP_BOX_LAYER) >= 0:
            mapBoxLayerId = iLayer
        if name.find(MAP_CLIP_LAYER) >= 0:
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
                if geometry.GetPointCount() > 0 \
                        and geometry.GetX(0) == geometry.GetX(geometry.GetPointCount() - 1) \
                        and geometry.GetY(0) == geometry.GetY(geometry.GetPointCount() - 1):
                    mapBoxGeometry = geometry
                    mapBoxPoints = geometry.GetPoints()
                    boxLL, boxLR, boxTL, boxTR = findConner(mapBoxPoints)

            # 영상영역 찾아 정보 추출
            if mapClipLayerId and mapClipGeometry is None:
                if geometry.GetPointCount() > 0 \
                        and geometry.GetX(0) == geometry.GetX(geometry.GetPointCount() - 1) \
                        and geometry.GetY(0) == geometry.GetY(geometry.GetPointCount() - 1):
                    mapClipGeometry = geometry
                    mapClipPoints = geometry.GetPoints()
                    imgLL, imgLR, imgTL, imgTR = findConner(mapClipPoints)

        pdfLayer.ResetReading()

        if mapBoxLayerId:
            mapBoxLayerId = None

        layerInfoList.append({'id': iLayer, 'name': name, "totalCount": totalFeatureCnt,
                              "pointCount": pointCount, "lineCount": lineCount, "polygonCount": polygonCount})

    print (boxLL, boxLR, boxTL, boxTR)

    affineTransform, _ = calcAffineTranform(boxLL, boxLR, boxTL, boxTR, tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)

    srcList = [[imgLL[0], imgLL[1]], [imgLR[0], imgLR[1]], [imgTL[0], imgTL[1]], [imgTR[0], imgTR[1]]]
    srcNpArray = np.array(srcList, dtype=np.float32)
    tgtNpArray = affineTransform(srcNpArray)

    return pdf, layerInfoList, affineTransform, crsId, mapNo, (tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR), \
           (tgtNpArray[0], tgtNpArray[1], tgtNpArray[2], tgtNpArray[3])


def importPdfVector(pdf, gpkg, layerInfoList, affineTransform, crsId, mapNo, bbox):
    prvTime = calcTime()

    print ("START importPdfVector")
    createdLayerName = []

    # 좌표계 정보 생성
    crs = osr.SpatialReference()
    crs.ImportFromEPSG(crsId)

    # Create QGIS Layer
    for layerInfo in layerInfoList:
        vPointLayer = None
        vLineLayer = None
        vPolygonLayer = None

        # 지도정보_ 로 시작하는 레이어만 임포트
        if not LAYER_FILTER.match(layerInfo["name"]):
            continue

        pdfLayer = pdf.GetLayerByIndex(layerInfo["id"])
        if pdfLayer.GetLayerDefn().GetFieldCount() > 0:
            print("FOUND ATTR!!!!")

        for ogrFeature in pdfLayer:
            geometry = ogrFeature.GetGeometryRef()
            fid = ogrFeature.GetFID()
            geomType = geometry.GetGeometryType()

            if geomType == ogr.wkbPoint or geomType == ogr.wkbMultiPoint:
                if not vPointLayer:
                    layerName = u"{}_Point".format(layerInfo["name"])
                    vPointLayer = gpkg.CreateLayer(layerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiPoint)
                    field = ogr.FieldDefn("GID", ogr.OFTInteger)
                    vPointLayer.CreateField(field)
                    createdLayerName.append(layerName)
                vLayer = vPointLayer
            elif geomType == ogr.wkbLineString or geomType == ogr.wkbMultiLineString:
                if not vLineLayer:
                    layerName = u"{}_Line".format(layerInfo["name"])
                    vLineLayer = gpkg.CreateLayer(layerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiLineString)
                    field = ogr.FieldDefn("GID", ogr.OFTInteger)
                    vLineLayer.CreateField(field)
                    createdLayerName.append(layerName)
                vLayer = vLineLayer
            elif geomType == ogr.wkbPolygon or geomType == ogr.wkbMultiPolygon:
                if not vPolygonLayer:
                    layerName = u"{}_Polygon".format(layerInfo["name"])
                    vPolygonLayer = gpkg.CreateLayer(layerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiPolygon)
                    field = ogr.FieldDefn("GID", ogr.OFTInteger)
                    vPolygonLayer.CreateField(field)
                    createdLayerName.append(layerName)
                vLayer = vPolygonLayer
            else:
                print ("[ERROR] Unknown geometry type: " + geometry.GetGeometryName())
                continue

            featureDefn = vLayer.GetLayerDefn()
            feature = ogr.Feature(featureDefn)
            feature.SetField("GID", fid)

            # collect vertex
            # if geometry.GetGeometryCount() <= 0:
            #     pointList = geometry.GetPoints()
            #     srcNpArray = np.array(pointList, dtype=np.float32)
            #
            #     # transform all vertex
            #     tgtNpList = affineTransform(srcNpArray)
            #
            #     # move vertex
            #     for i in range(0, len(srcNpArray)):
            #         geometry.SetPoint(i, tgtNpList[i][0], tgtNpList[i][1])
            # else:
            #     for geomId in range(geometry.GetGeometryCount()):
            #         geom = geometry.GetGeometryRef(geomId)
            #
            #         pointList = geom.GetPoints()
            #         srcNpArray = np.array(pointList, dtype=np.float32)
            #
            #
            #         # transform all vertex
            #         tgtNpList = affineTransform(srcNpArray)
            #
            #         # move vertex
            #         for i in range(0, len(srcNpArray)):
            #             geom.SetPoint(i, tgtNpList[i][0], tgtNpList[i][1])

            g_TransformGeom(geometry, affineTransform)

            feature.SetGeometry(geometry)
            vLayer.CreateFeature(feature)

            feature = None

        print u"Layer: {} - ".format(layerInfo["name"]),
        prvTime = calcTime(prvTime)

    return createdLayerName


def g_TransformGeom(geometry, affineTransform):
    if geometry.GetGeometryCount() == 0:
        pointList = geometry.GetPoints()
        srcNpArray = np.array(pointList, dtype=np.float32)

        # transform all vertex
        tgtNpList = affineTransform(srcNpArray)

        # move vertex
        for i in range(0, len(srcNpArray)):
            geometry.SetPoint(i, tgtNpList[i][0], tgtNpList[i][1])
    else:
        for geomId in range(geometry.GetGeometryCount()):
            subGeom = geometry.GetGeometryRef(geomId)
            g_TransformGeom(subGeom, affineTransform)


def importPdfRaster(pdfFilePath, gpkgFileNale, crsId, imgBox):
    try:
        fh = open(pdfFilePath, "rb")
        pdfObj = PyPDF2.PdfFileReader(fh)
    except RuntimeError, e:
        return

    pageObj = pdfObj.getPage(0)

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

            # 작은 이미지 무시
            if size[0] < SKIP_IMAGE_WIDTH:
                continue

            colorSpace = xObject[obj]['/ColorSpace']
            if colorSpace == '/DeviceRGB':
                mode = "RGB"
            elif colorSpace == '/DeviceCMYK':
                mode = "CMYK"
            elif colorSpace == '/DeviceGray':
                mode = "L"
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
                        elif filterType == ():
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

    fh.close()
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
        del images[key]

    images.clear()

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

    _, matrix = calcAffineTranform(
        srcNpArray[0], srcNpArray[1], srcNpArray[2], srcNpArray[3],
        imgBox[0], imgBox[1], imgBox[2], imgBox[3]
    )

    driver = gdal.GetDriverByName("GPKG")
    dataset = driver.Create(
        gpkgFileNale,
        mergedWidth,
        mergedHeight,
        3,
        gdal.GDT_Byte,
        options=["APPEND_SUBDATASET=YES", "RASTER_TABLE=PHOTO_IMAGE", "TILE_FORMAT=JPEG"]
    )

    dataset.SetProjection(crs_wkt)
    xScale = math.sqrt(matrix[0][0] ** 2 + matrix[1][0] ** 2)
    yScale = math.sqrt(matrix[0][1] ** 2 + matrix[1][1] ** 2)
    dataset.SetGeoTransform((matrix[0][2], xScale, 0.0, matrix[1][2], 0.0, -yScale))

    band1 = np.array(list(mergedImage.getdata(0))).reshape(-1, mergedWidth)
    band2 = np.array(list(mergedImage.getdata(1))).reshape(-1, mergedWidth)
    band3 = np.array(list(mergedImage.getdata(2))).reshape(-1, mergedWidth)

    dataset.GetRasterBand(1).WriteArray(band1)
    dataset.GetRasterBand(2).WriteArray(band2)
    dataset.GetRasterBand(3).WriteArray(band3)
    dataset.FlushCache()

    mergedImage.close()
    del mergedImage
    del band1
    del band2
    del band3
    del dataset

    return True


def createGeoPackage(gpkgFilePath):
    gpkg = None

    try:
        if os.path.isfile(gpkgFilePath):
            os.remove(gpkgFilePath)
    except Exception, e:
        message(u"{} 파일을 다시 만들 수 없습니다. 아마 사용중인 듯 합니다.".format(gpkgFilePath))
        return

    driver = ogr.GetDriverByName("GPKG")
    # opening the FileGDB
    try:
        gpkg = driver.CreateDataSource(gpkgFilePath)
    except Exception, e:
        print e

    return gpkg


def openGeoPackage(gpkgFilePath):
    # 래스터 로딩
    try:
        layer = iface.addRasterLayer(gpkgFilePath, u"영상", "gdal")
    except:
        layer = None
    if not layer:
        print u"Layer {} failed to load!".format(u"영상")

    # 벡터 로딩
    gpkg = None
    try:
        gpkg = ogr.Open(gpkgFilePath)

        for layer in gpkg:
            layerName = unicode(layer.GetName().decode('utf-8'))

            try:
                uri = u"{}|layername={}".format(gpkgFilePath, layerName)
                layer = iface.addVectorLayer(uri, None, "ogr")
            except:
                layer = None

            if not layer:
                print u"Layer {} failed to load!".format(layerName)
    finally:
        pass
        # if gpkg:
        #     del gpkg


def calcTime(prvTime=None):
    if prvTime is None:
        return timeit.default_timer()

    crr = timeit.default_timer()
    print("{}ms".format(int((crr - prvTime) * 1000)))

    return crr


def message(str):
    print(str)


def main():
    # try:
    #     iface
    #     pdfFilePath = QFileDialog.getOpenFileName(caption=u"국토지리정보원 온맵 PDF 파일 선택", filter=u"온맵(*.pdf)")
    # except:
    #     pdfFilePath = PDF_FILE_NAME
    pdfFilePath = PDF_FILE_NAME

    if pdfFilePath is None:
        return

    # GeoPackage 파일 경로를 PDF와 같은 경로로 정한다.
    base, ext = os.path.splitext(pdfFilePath)
    gpkgFilePath = base + ".gpkg"

    gpkg = createGeoPackage(gpkgFilePath)
    if gpkg is None:
        return

    # clear canvas
    try:
        QgsMapLayerRegistry.instance().removeAllMapLayers()
    except:
        pass

    print("START")
    prvTime = calcTime()

    # PDF에서 레이어와 좌표계 변환 정보 추출
    try:
        pdf, layerInfoList, affineTransform, crsId, mapNo, bbox, imgBox = getPdfInformation(pdfFilePath)
    except TypeError:
        message(u"PDF 파일에서 정보를 추출하지 못했습니다. 온맵 PDF가 아닌 듯 합니다.")
        return

    print "getPdfInformation: ",
    prvTime = calcTime(prvTime)

    importPdfVector(pdf, gpkg, layerInfoList, affineTransform, crsId, mapNo, bbox)
    # del gpkg

    print "importPdfVector: ",
    prvTime = calcTime(prvTime)

    # clean close
    del pdf

    importPdfRaster(pdfFilePath, gpkgFilePath, crsId, imgBox)
    print "importPdfRaster: ",
    prvTime = calcTime(prvTime)

    openGeoPackage(gpkgFilePath)

    # Project 좌표계로 변환하여 화면을 이동해야 한다.
    try:
        canvas = iface.mapCanvas()
        mapRenderer = canvas.mapRenderer()
        srs = mapRenderer.destinationCrs()
        mapProj = Proj(init="EPSG:{}".format(crsId))
        projProj = Proj(init=srs.authid())
        minPnt = transform(mapProj, projProj, bbox[0][0], bbox[0][1])
        maxPnt = transform(mapProj, projProj, bbox[3][0], bbox[3][1])
        canvas.setExtent(QgsRectangle(minPnt[0], minPnt[1], maxPnt[0], maxPnt[1]))
        canvas.refresh()
    except:
        pass

    print("COMPLETED!")


###################
# RUN Main function
if __name__ == '__console__':
    main()

if __name__ == '__main__':
    main()
