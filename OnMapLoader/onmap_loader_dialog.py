# -*- coding: utf-8 -*-
"""
/***************************************************************************
 OnMapLoaderDialog
                                 A QGIS plugin
 Tool for loading OnMap(Korea NGII PDF Map) to QGIS
                             -------------------
        begin                : 2017-09-08
        git sha              : $Format:%H$
        copyright            : (C) 2017 by BJ Jang / Gaia3D
        email                : jangbi882@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4 import QtGui, uic
from qgis.core import *

import re
import numpy as np
import copy

# import OGR
from osgeo import ogr, gdal, osr
from pyproj import Proj, transform

try:
    import PyPDF2
    from PyPDF2.filters import *
    from PyPDF2.pdf import *
except:
    import pip
    pip.main(['install', "PyPDF2"])
    import PyPDF2
    from PyPDF2.filters import *
    from PyPDF2.pdf import *

from PIL import Image
from io import BytesIO

# 기본 설정값
LAYER_FILTER = re.compile(u"^지도정보_")
MAP_BOX_LAYER = u"지도정보_도곽"
MAP_CLIP_LAYER = u"지도정보_Other"
NUM_FILTER = re.compile('.*_(\d*)')
SKIP_IMAGE_WIDTH = 2000


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'onmap_loader_dialog_base.ui'))


#########################
# UI FUNCTION
#########################
def force_gui_update():
    QgsApplication.processEvents(QEventLoop.ExcludeUserInputEvents)


def addTreeItem(parent, text):
    itm = QtGui.QTreeWidgetItem(parent)
    itm.setText(0, text)
    itm.setFlags(itm.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
    itm.setCheckState(0, Qt.Checked)
    return itm


#########################
# ANALYSIS FUNCTION
#########################
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
        raise NotImplementedError(u"죄송합니다.25만 도엽은 지원되지 않습니다.")
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


#########################
# MAIN CLASS
#########################
class OnMapLoaderDialog(QtGui.QDialog, FORM_CLASS):
    iface = None
    pdfPath = None
    gpkgPath = None
    pdf = None
    layerInfoList = None
    affineTransform = None
    crsId = None
    mapNo = None
    bbox = None
    imgBox = None
    gpkg = None

    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OnMapLoaderDialog, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        self.iface = iface
        self._connect_action()

    def error(self, msg):
        self.editLog.appendHtml(u'<font color="red">{}</font>'.format(msg))

    def info(self, msg):
        self.editLog.appendPlainText(msg)

    def debug(self, msg):
        self.editLog.appendHtml(u'<font color="gray">{}</font>'.format(msg))

    def _connect_action(self):
        self.connect(self.btnSrcFile, SIGNAL("clicked()"), self._on_click_btnSrcFile)
        self.connect(self.btnTgtFile, SIGNAL("clicked()"), self._on_click_btnTgtFile)
        self.connect(self.btnStart, SIGNAL("clicked()"), self._on_click_btnStart)
        self.connect(self.btnStop, SIGNAL("clicked()"), self._on_click_btnStop)
        self.connect(self.btnStop, SIGNAL("textChanged()"), self._on_click_btnStop)
        self.connect(self.btnStop, SIGNAL("textChanged()"), self._on_click_btnStop)

    def _on_click_btnSrcFile(self):
        qfd = QFileDialog()
        title = u"온맵(PDF) 파일 열기"
        ext = u"온맵(*.pdf)"
        if self.pdfPath is None:
            pdfPath = os.path.expanduser("~")
        else:
            pdfPath = os.path.split(self.pdfPath)[0]
        path = QFileDialog.getOpenFileName(qfd, caption=title, directory=pdfPath, filter=ext)

        if not path:
            return
        self.pdfPath = path
        self.edtSrcFile.setText(self.pdfPath)

        base, _ = os.path.splitext(path)
        self.gpkgPath = base + ".gpkg"

        self.edtTgtFile.setText(self.gpkgPath)

        # Clear log window
        QgsApplication.setOverrideCursor(Qt.WaitCursor)
        self.editLog.clear()

        # Layer List
        self.fillLayerTreeFromPdf()
        QgsApplication.restoreOverrideCursor()
        self.info(u"레이어를 선택하고 [변환 시작] 버튼을 눌러주세요.")

    def _on_click_btnTgtFile(self):
        qfd = QFileDialog()
        title = u"생생될 지오패키지(GPKG) 파일 선택"
        ext = u"지오패키지(*.gpkg)"
        if self.gpkgPath is None:
            gpkgPath = os.path.expanduser("~")
        else:
            gpkgPath = self.gpkgPath
        path = QFileDialog.getSaveFileName(qfd, caption=title, directory=gpkgPath, filter=ext)

        if not path:
            return
        self.gpkgPath = path
        self.edtTgtFile.setText(self.gpkgPath)

        # TODO: gpkg에서 레이어 리스트 읽어 오기

    def _on_click_btnStart(self):
        self.pdfPath = self.edtSrcFile.text()
        self.gpkgPath = self.edtTgtFile.text()

        if not os.path.exists(self.pdfPath):
            self.error(u"선택한 온맵(PDF) 파일이 존재하지 않습니다.")
            return

        if not self.pdf:
            rc = self.fillLayerTreeFromPdf()
            if not rc:
                return

        # 이미 있는 gpkg 이용할지 물어보기
        if os.path.exists(self.gpkgPath):
            rc = QMessageBox.question(self, u"GeoPackage 재활용",
                                      u"이미 지오패키지 파일이 있습니다.\n"
                                      u"다시 변환하지 않고 이 파일을 이용할까요?\n\n"
                                      u"변환을 생략하면 더 빨리 열 수 있습니다.",
                                      QMessageBox.Yes | QMessageBox.No)
            if rc != QMessageBox.Yes:
                rc = self.createGeoPackage()
                if not rc:
                    QMessageBox.information(self, u"오류"
                                            , u"지오패키지(GPKG) 파일을 만들지 못해 중단됩니다.")
                    return
                self.importPdfVector()
                self.importPdfRaster()
                pass

        self.openGeoPackage()

        # Project 좌표계로 변환하여 화면을 이동해야 한다.
        try:
            canvas = self.iface.mapCanvas()
            mapRenderer = canvas.mapRenderer()
            srs = mapRenderer.destinationCrs()
            mapProj = Proj(init="EPSG:{}".format(self.crsId))
            projProj = Proj(init=srs.authid())
            minPnt = transform(mapProj, projProj, self.bbox[0][0], self.bbox[0][1])
            maxPnt = transform(mapProj, projProj, self.bbox[3][0], self.bbox[3][1])
            canvas.setExtent(QgsRectangle(minPnt[0], minPnt[1], maxPnt[0], maxPnt[1]))
            canvas.refresh()
        except:
            pass

    def _on_click_btnStop(self):
        rc = QMessageBox.question(self, u"작업 강제 중지",
                                  u"현재 작업을 강제로 중지하시겠습니까?\n\n"
                                  u"작업 중지는 오류의 원인이 될 수도 있습니다.",
                                  QMessageBox.Yes | QMessageBox.No)

    def fillLayerTreeFromPdf(self):
        self.pdfPath = self.edtSrcFile.text()
        rc =  self.getPdfInformation()
        if not rc:
            self.error(u"PDF 파일에서 정보를 추출하지 못했습니다. 온맵 PDF가 아닌 듯 합니다.")
            return

        self.treeLayer.clear()
        parentList = dict()
        parentList[0] = self.treeLayer
        titleList = dict()
        titleList[0] = "ROOT"
        for layerInfo in self.layerInfoList:
            name = layerInfo["name"]
            if not LAYER_FILTER.match(name):
                continue
            nameList = name.split("_")
            for i in range(len(nameList)):
                title = nameList[i]
                if not titleList.has_key(i+1):
                    level = i+1
                    titleList[level] = title
                    item = addTreeItem(parentList[level-1], title)
                    parentList[level] = item
                    if level <= 2:
                        item.setExpanded(True)
                    else:
                        item.setExpanded(False)
                elif titleList[i+1] != title:
                    level = i+1
                    for j in range(level, len(titleList)):
                        titleList.pop(j)
                        parentList.pop(j)
                    titleList[level] = title
                    item = addTreeItem(parentList[level-1], title)
                    parentList[level] = item
                    if level <= 2:
                        item.setExpanded(True)
                    else:
                        item.setExpanded(False)

        # TODO: 영상 추가
        return True

    def getPdfInformation(self):
        self.lblMainWork.setText(u"선택한 온맵 파일 분석중...")
        self.progressMainWork.setMinimum(0)
        self.progressMainWork.setMaximum(0)
        self.info(u"PDF 파일에서 정보추출 시작...")
        force_gui_update()

        mapNo = findMapNo(os.path.basename(self.pdfPath))
        if mapNo is None:
            return

        try:
            boxLL, boxLR, boxTL, boxTR = mapNoToMapBox(mapNo)
        except NotImplementedError as e:
            self.error(repr(e))
        except:
            self.error(u"해석할 수 없는 도엽명이어서 중단됩니다.")
            return

        # get the driver
        srcDriver = ogr.GetDriverByName("PDF")

        # opening the PDF
        try:
            pdf = srcDriver.Open(self.pdfPath, 0)
        except Exception, e:
            print e
            return

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
                force_gui_update()
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

        self.info(u"정보추출 완료.")
        self.lblMainWork.setText(u"작업 대기중")
        self.progressMainWork.setMinimum(0)
        self.progressMainWork.setMaximum(100)

        # Return Values
        self.pdf = pdf
        self.layerInfoList = layerInfoList
        self.affineTransform =affineTransform
        self.crsId = crsId
        self.mapNo = mapNo
        self.bbox = (tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)
        self.imgBox = (tgtNpArray[0], tgtNpArray[1], tgtNpArray[2], tgtNpArray[3])

        return True

    def createGeoPackage(self):
        gpkg = None

        try:
            if os.path.isfile(self.gpkgPath):
                os.remove(self.gpkgPath)
        except Exception, e:
            self.error(u"{} 파일을 다시 만들 수 없습니다. 아마 사용중인 듯 합니다.".format(self.gpkgPath))
            return

        driver = ogr.GetDriverByName("GPKG")
        # opening the FileGDB
        try:
            gpkg = gdal.OpenEx(self.gpkgPath, gdal.OF_ALL)
            if gpkg is None:
                gpkg = driver.CreateDataSource(self.gpkgPath)
        except Exception, e:
            print e
            return

        self.gpkg = gpkg
        return True

    def importPdfVector(self):
        self.info (u"PDF에서 벡터정보 추출 시작...")
        createdLayerName = []

        # 좌표계 정보 생성
        crs = osr.SpatialReference()
        crs.ImportFromEPSG(self.crsId)

        # Create QGIS Layer
        for layerInfo in self.layerInfoList:
            vPointLayer = None
            vLineLayer = None
            vPolygonLayer = None

            # TODO: 사용자로 부터 옵션 받게 수정
            # 지도정보_ 로 시작하는 레이어만 임포트
            if not LAYER_FILTER.match(layerInfo["name"]):
                continue

            pdfLayer = self.pdf.GetLayerByIndex(layerInfo["id"])
            if pdfLayer.GetLayerDefn().GetFieldCount() > 0:
                print("FOUND ATTR!!!!")

            for ogrFeature in pdfLayer:
                geometry = ogrFeature.GetGeometryRef()
                fid = ogrFeature.GetFID()
                geomType = geometry.GetGeometryType()

                if geomType == ogr.wkbPoint or geomType == ogr.wkbMultiPoint:
                    if not vPointLayer:
                        layerName = u"{}_Point".format(layerInfo["name"])
                        vPointLayer = self.gpkg.CreateLayer(layerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiPoint)
                        field = ogr.FieldDefn("GID", ogr.OFTInteger)
                        vPointLayer.CreateField(field)
                        createdLayerName.append(layerName)
                    vLayer = vPointLayer
                elif geomType == ogr.wkbLineString or geomType == ogr.wkbMultiLineString:
                    if not vLineLayer:
                        layerName = u"{}_Line".format(layerInfo["name"])
                        vLineLayer = self.gpkg.CreateLayer(layerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiLineString)
                        field = ogr.FieldDefn("GID", ogr.OFTInteger)
                        vLineLayer.CreateField(field)
                        createdLayerName.append(layerName)
                    vLayer = vLineLayer
                elif geomType == ogr.wkbPolygon or geomType == ogr.wkbMultiPolygon:
                    if not vPolygonLayer:
                        layerName = u"{}_Polygon".format(layerInfo["name"])
                        vPolygonLayer = self.gpkg.CreateLayer(layerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiPolygon)
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
                if geometry.GetGeometryCount() <= 0:
                    pointList = geometry.GetPoints()
                    srcNpArray = np.array(pointList, dtype=np.float32)

                    # transform all vertex
                    tgtNpList = self.affineTransform(srcNpArray)

                    # move vertex
                    for i in range(0, len(srcNpArray)):
                        geometry.SetPoint(i, tgtNpList[i][0], tgtNpList[i][1])
                else:
                    for geomId in range(geometry.GetGeometryCount()):
                        geom = geometry.GetGeometryRef(geomId)
                        pointList = geom.GetPoints()
                        srcNpArray = np.array(pointList, dtype=np.float32)

                        # transform all vertex
                        tgtNpList = self.affineTransform(srcNpArray)

                        # move vertex
                        for i in range(0, len(srcNpArray)):
                            geom.SetPoint(i, tgtNpList[i][0], tgtNpList[i][1])

                feature.SetGeometry(geometry)
                vLayer.CreateFeature(feature)
                feature = None

            print u"Layer: {} - ".format(layerInfo["name"]),

        return True

    def importPdfRaster(self):
        try:
            fh = open(self.pdfPath, "rb")
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
        crs.ImportFromEPSG(self.crsId)
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
            self.imgBox[0], self.imgBox[1], self.imgBox[2], self.imgBox[3]
        )

        driver = gdal.GetDriverByName("GPKG")
        dataset = driver.Create(
            self.gpkgPath,
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

    def openGeoPackage(self):
        # 래스터 로딩
        try:
            layer = self.iface.addRasterLayer(self.gpkgPath, u"영상", "gdal")
        except:
            layer = None
        if not layer:
            self.error(u"레이어 {} 읽기 실패".format(u"영상"))

        # 벡터 로딩
        gpkg = None
        try:
            gpkg = ogr.Open(self.gpkgPath)

            for layer in gpkg:
                layerName = unicode(layer.GetName().decode('utf-8'))

                try:
                    uri = u"{}|layername={}".format(self.gpkgPath, layerName)
                    layer = self.iface.addVectorLayer(uri, None, "ogr")
                except:
                    layer = None

                if not layer:
                    self.error(u"레이어 {} 읽기 실패".format(layerName))
        finally:
            if gpkg:
                del gpkg

        return True
