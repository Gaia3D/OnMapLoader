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
import timeit

# import OGR
from osgeo import ogr, gdal, osr
from pyproj import Proj, transform


# 기본 설정값
LAYER_FILTER = re.compile(u"^지도정보_")
MAP_BOX_LAYER = u"지도정보_도곽"
MAP_CLIP_LAYER = u"지도정보_Other"
NUM_FILTER = re.compile('.*_(\d*)')
SKIP_IMAGE_WIDTH = 2000


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'onmap_loader_dialog_base.ui'))


def force_gui_update():
    QgsApplication.processEvents(QEventLoop.ExcludeUserInputEvents)


def addTreeItem(parent, text):
    itm = QtGui.QTreeWidgetItem(parent)
    itm.setText(0, text)
    itm.setFlags(itm.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
    itm.setCheckState(0, Qt.Checked)
    return itm


class OnMapLoaderDialog(QtGui.QDialog, FORM_CLASS):
    iface = None
    pdfPath = None

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

    def setCursor(self, cursor):
        cursor = QCursor()
        cursor.setShape(Qt.WhatsThisCursor)
        QApplication.instance().setOverrideCursor(cursor)

    def _connect_action(self):
        self.connect(self.btnSrcFile, SIGNAL("clicked()"), self._on_click_btnSrcFile)
        self.connect(self.btnTgtFile, SIGNAL("clicked()"), self._on_click_btnTgtFile)

    def _on_click_btnSrcFile(self):
        qfd = QFileDialog()
        title = u"온맵(PDF) 파일 열기"
        ext = u"온맵(*.pdf)"
        if self.pdfPath is None:
            pdfPath = os.path.expanduser("~")
        else:
            pdfPath = os.path.split(self.pdfPath)
        path = QFileDialog.getOpenFileName(qfd, title, pdfPath, filter=ext)

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
        QgsApplication.restoreOverrideCursor()

        # TODO: 이미 있는 gpkg 이용할지 물어보기

        # Layer List
        self.fillLayerList()


    def _on_click_btnTgtFile(self):
        qfd = QFileDialog()
        title = u"생생될 지오패키지(GPKG) 파일 선택"
        ext = u"지오패키지(*.gpkg)"
        if self.gpkgPath is None:
            gpkgPath = os.path.expanduser("~")
        else:
            gpkgPath = os.path.split(self.gpkgPath)
        path = QFileDialog.getSaveFileName(qfd, title, gpkgPath, filter=ext)

        if not path:
            return
        self.gpkgPath = path
        self.edtTgtFile.setText(self.gpkgPath)

    def fillLayerList(self):
        try:
            pdf, layerInfoList, affineTransform, crsId, mapNo, bbox, imgBox \
                = self.getPdfInformation(self.edtSrcFile.text())
        except TypeError:
            self.error(u"PDF 파일에서 정보를 추출하지 못했습니다. 온맵 PDF가 아닌 듯 합니다.")
            return

        self.treeLayer.clear()
        parentList = {}
        parentList[0] = self.treeLayer
        titleList = {}
        titleList[0] = "ROOT"
        for layerInfo in layerInfoList:
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

    ########
    def findMapNo(self, fileBase):
        MAP_NO_FILTER = re.compile(u".*온맵_(.*)$")
        res = MAP_NO_FILTER.search(fileBase)
        if res:
            return os.path.splitext(res.group(1))[0]
        else:
            return None

    def mapNoToMapBox(self, mapNo):
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
            self.error(u"죄송합니다.25만 도엽은 지원되지 않습니다.")
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

    def findConner(self, points):
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

    # REFER: https://stackoverflow.com/questions/20546182/how-to-perform-coordinates-affine-transformation-using-python-part-2
    def calcAffineTranform(self, srcP1, srcP2, srcP3, srcP4, tgtP1, tgtP2, tgtP3, tgtP4):
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

    def getPdfInformation(self, pdfFilePath):
        self.lblMainWork.setText(u"선택한 온맵 파일 분석중...")
        self.progressMainWork.setMinimum(0)
        self.progressMainWork.setMaximum(0)
        self.info(u"PDF 파일에서 정보추출 시작...")
        force_gui_update()

        mapNo = self.findMapNo(os.path.basename(pdfFilePath))
        if mapNo is None:
            return

        try:
            boxLL, boxLR, boxTL, boxTR = self.mapNoToMapBox(mapNo)
        except:
            self.error(u"해석할 수 없는 도엽명이어서 중단됩니다.")
            return

        # get the driver
        srcDriver = ogr.GetDriverByName("PDF")

        # opening the PDF
        try:
            pdf = srcDriver.Open(pdfFilePath, 0)
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
                        boxLL, boxLR, boxTL, boxTR = self.findConner(mapBoxPoints)

                # 영상영역 찾아 정보 추출
                if mapClipLayerId and mapClipGeometry is None:
                    if geometry.GetPointCount() > 0 \
                            and geometry.GetX(0) == geometry.GetX(geometry.GetPointCount() - 1) \
                            and geometry.GetY(0) == geometry.GetY(geometry.GetPointCount() - 1):
                        mapClipGeometry = geometry
                        mapClipPoints = geometry.GetPoints()
                        imgLL, imgLR, imgTL, imgTR = self.findConner(mapClipPoints)

            pdfLayer.ResetReading()

            if mapBoxLayerId:
                mapBoxLayerId = None

            layerInfoList.append({'id': iLayer, 'name': name, "totalCount": totalFeatureCnt,
                                  "pointCount": pointCount, "lineCount": lineCount, "polygonCount": polygonCount})

        print (boxLL, boxLR, boxTL, boxTR)

        affineTransform, _ = self.calcAffineTranform(boxLL, boxLR, boxTL, boxTR, tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)

        srcList = [[imgLL[0], imgLL[1]], [imgLR[0], imgLR[1]], [imgTL[0], imgTL[1]], [imgTR[0], imgTR[1]]]
        srcNpArray = np.array(srcList, dtype=np.float32)
        tgtNpArray = affineTransform(srcNpArray)

        self.lblMainWork.setText(u"작업 대기중")
        self.progressMainWork.setMinimum(0)
        self.progressMainWork.setMaximum(100)

        return pdf, layerInfoList, affineTransform, crsId, mapNo, (tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR), \
               (tgtNpArray[0], tgtNpArray[1], tgtNpArray[2], tgtNpArray[3])
