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
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4 import QtGui, uic
from qgis.core import *

import re
import numpy as np
import copy
import ConfigParser

import sys
import os

# import OGR
from osgeo import ogr, gdal, osr
gdal.UseExceptions()

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
# ConfigParser Monkey Patch
#########################
# ConfigParser에 한글 문제가 있어 해결
def write(self, fp):
    """Write an .ini-format representation of the configuration state."""
    if self._defaults:
        fp.write("[%s]\n" % "DEFAULT")
        for (key, value) in self._defaults.items():
            fp.write("%s = %s\n" % (key, str(value).replace('\n', '\n\t')))
        fp.write("\n")
    for section in self._sections:
        fp.write("[%s]\n" % section)
        for (key, value) in self._sections[section].items():
            if key == "__name__":
                continue
            if (value is not None) or (self._optcre == self.OPTCRE):
                if type(value) == unicode:
                    value = ''.join(value).encode('utf-8')
                else:
                    value = str(value)
                value = value.replace('\n', '\n\t')
                key = " = ".join((key, value))
            fp.write("%s\n" % (key))
        fp.write("\n")
ConfigParser.RawConfigParser.write = write


#########################
# Define User Exception
#########################
class StoppedByUserException(Exception):
    def __init__(self, message = ""):
        # Call the base class constructor with the parameters it needs
        super(StoppedByUserException, self).__init__(message)


#########################
# UI FUNCTION
#########################
def force_gui_update():
    QgsApplication.processEvents(QEventLoop.ExcludeUserInputEvents)


def addTreeItem(parent, text):
    item = QtGui.QTreeWidgetItem(parent)
    item.setText(0, text)
    item.setFlags(item.flags() | Qt.ItemIsTristate | Qt.ItemIsUserCheckable)
    item.setCheckState(0, Qt.Checked)
    return item


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
    res = re.search("(?i).*_(.*)\.pdf$", fileBase)
    if res:
        return res.group(1)
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
        # raise NotImplementedError(u"죄송합니다.25만 도엽은 지원되지 않습니다.")
        raise NotImplementedError(tr("Sorry, 250k scale map boxes are not supported."))
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
    gpkglayerInfoList = None
    affineTransform = None
    crsId = None
    mapNo = None
    bbox = None
    imgBox = None
    gpkg = None
    configFile = None
    isOnProcessing = False
    forceStop = False
    readMode = "PDF"

    enableDebug = False
    enableInfo = True

    def __init__(self, iface, parent=None):
        """Constructor."""
        super(OnMapLoaderDialog, self).__init__(parent)

        self.configFile = os.path.join(QgsApplication.qgisSettingsDirPath(), 'onmap_loader.ini')
        self.setupUi(self)
        self._set_ui_text()
        self.edtSrcFile.setFocus()
        self.iface = iface
        self._connect_action()
        self.readConfig()
        # self.order(u"변환할 온맵(PDF)이나 이전에 변환된 지오패키지(GPKG)를 선택해 주세요.")
        self.order(self.tr("Please select an OnMap (*.pdf) to convert or a previously converted GeoPackage (*.gpkg)."))
        # 중지 기능 구현 실패로 일단 안보이게
        self.btnStop.hide()

    def tr(self, message):
        return QCoreApplication.translate('OnMapLoaderDialog', message)

    def error(self, msg):
        self.editLog.appendHtml(u'<font color="red"><b>{}</b></font>'.format(msg))

    def info(self, msg):
        if not self.enableInfo:
            return
        self.editLog.appendPlainText(msg)

    def debug(self, msg):
        if not self.enableDebug:
            return
        self.editLog.appendHtml(u'<font color="gray">{}</font>'.format(msg))

    def order(self, msg):
        self.editLog.appendHtml(u'<font color="blue"><b>{}</b></font>'.format(msg))

    def _set_ui_text(self):
        # self.setWindowTitle(u"온맵(지리원 PDF 지도) 로더")
        self.setWindowTitle(self.tr("OnMap(NGII PDF map) Loader"))
        # self.lblMainWork.setText(self.tr("전체 작업 진행상황"))
        self.lblMainWork.setText(self.tr("Overall work progress"))
        # self.lblSubWork.setText(self.tr("현재 작업 진행상황"))
        self.lblSubWork.setText(self.tr("Current work progress"))
        # self.lblTgtFile.setText(self.tr("변환된 공간정보가 저장될 지오패키지(GPKG) 파일:"))
        self.lblTgtFile.setText(self.tr("GeoPackage(GPKG) file for store converted information:"))
        # self.btnTgtFile.setText(self.tr("선택..."))
        self.btnTgtFile.setText(self.tr("Browse..."))
        # self.btnStop.setText(self.tr("작업중지"))
        self.btnStop.setText(self.tr("Abort working"))
        # self.btnStart.setText(self.tr("온맵 변환 시작"))
        self.btnStart.setText(self.tr("Start OnMap conversion"))
        # self.lblSrcFile.setText(self.tr("변환대상 온맵(PDF) 파일:"))
        self.lblSrcFile.setText(self.tr("Conversion target OnMap(PDF) file:"))
        # self.btnSrcFile.setText(self.tr("선택..."))
        self.btnSrcFile.setText(self.tr("Browse..."))
        # self.lblSelLayer.setText(self.tr("가져올 레이어 선택:"))
        self.lblSelLayer.setText(self.tr("Select layer to import:"))


    def _connect_action(self):
        self.connect(self.btnSrcFile, SIGNAL("clicked()"), self._on_click_btnSrcFile)
        self.connect(self.btnTgtFile, SIGNAL("clicked()"), self._on_click_btnTgtFile)
        self.connect(self.btnStart, SIGNAL("clicked()"), self._on_click_btnStart)
        self.connect(self.btnStop, SIGNAL("clicked()"), self._on_click_btnStop)

    def _on_click_btnSrcFile(self):
        qfd = QFileDialog()
        # title = u"온맵(PDF) 파일 열기"
        title = tr("Open OnMap(PDF) file")
        # ext = u"온맵(*.pdf)"
        ext = tr("OnMap(*.pdf)")
        pdfPath = os.path.dirname(self.pdfPath)
        path = QFileDialog.getOpenFileName(qfd, caption=title, directory=pdfPath, filter=ext)

        if not path:
            return
        self.pdfPath = path
        self.edtSrcFile.setText(self.pdfPath)

        base, _ = os.path.splitext(path)
        self.gpkgPath = base + ".gpkg"
        self.edtTgtFile.setText(self.gpkgPath)

        # GPKG가 존재하면 재사용 확인
        rc = None
        if os.path.exists(self.gpkgPath):
            # rc = QMessageBox.question(self, u"GeoPackage 재활용 여부 확인",
            #                           u"이미 지오패키지 파일이 있습니다.\n"
            #                           u"다시 변환하지 않고 이 파일을 이용할까요?\n\n"
            #                           u"[예]를 누르면 변환을 생략하고 더 빨리 열 수 있습니다.\n"
            #                           u"[아니오]를 누르면 지오패키지 파일을 다시 생성합니다.",
            #                           QMessageBox.Yes | QMessageBox.No)
            rc = QMessageBox.question(self, self.tr("Recycle GeoPackage?"),
                                      self.tr("You already have a GeoPackage file.\n"
                                              "Do you want to use this file without converting it again?\n\n"
                                              "If you click [Yes], you can omit the conversion and open it faster.\n"
                                              "Click [No] to regenerate the geo-package file."),
                                      QMessageBox.Yes | QMessageBox.No)

        if rc != QMessageBox.Yes:
            # PDF에서 읽는 경우
            self.readMode = "PDF"
            # self.btnStart.setText(u"온맵 변환 시작")
            self.btnStart.setText(self.tr("Convert OnMap"))
            rc = self.fillLayerTreeFromPdf()
            if not rc:
                # self.error(u"온맵(PDF) 파일에서 지리정보를 추출하지 못했습니다. 온맵이 아닌 듯 합니다.")
                self.error(self.tr("Failed to extract geographic information from OnMap(PDF) file. It does not seem to be OnMap."))
                return

            # self.order(u"레이어를 선택하고 [온맵 변환 시작] 버튼을 눌러주세요.")
            self.order(self.tr("Select the layer and press the [Convert OnMap] button."))
            self.btnStart.setEnabled(True)
        else:
            # GPKG에서 읽는 경우
            self.readMode = "GPKG"
            # self.btnStart.setText(u"지오패키지 읽기 시작")
            self.btnStart.setText(self.tr("Read GeoPackage"))
            rc = self.fillLayerTreeFromGpkg()
            if not rc:
                # self.error(u"지오패키지(GPKG) 파일에서 레이어 정보를 읽지 못했습니다.")
                self.error(self.tr("Failed to read layer information from GeoPackage(GPKG) file."))
                return

            # self.order(u"레이어를 선택하고 [지오패키지 읽기 시작] 버튼을 눌러주세요.")
            self.order(self.tr("Select the layer and press the [Read GeoPackage] button."))
            self.btnStart.setEnabled(True)

        self.writeConfig()

    def _on_click_btnTgtFile(self):
        qfd = QFileDialog()
        # title = u"생생될 지오패키지(GPKG) 파일 선택"
        title = self.tr("Select a target GeoPackage(GPKG) file")
        # ext = u"지오패키지(*.gpkg)"
        ext = self.tr("GeoPackage(*.gpkg)")
        gpkgPath = os.path.dirname(self.gpkgPath)
        path = QFileDialog.getOpenFileName(qfd, caption=title, directory=gpkgPath, filter=ext)

        if not path:
            return
        self.gpkgPath = path
        self.edtTgtFile.setText(self.gpkgPath)

        self.readMode = "GPKG"
        # self.btnStart.setText(u"지오패키지 읽기 시작")
        self.btnStart.setText(self.tr("Read GeoPackage"))
        rc = self.fillLayerTreeFromGpkg()
        if not rc:
            # self.error(u"지오패키지(GPKG) 파일에서 레이어 정보를 읽지 못했습니다.")
            self.error(self.tr("Failed to read layer information from GeoPackage(GPKG) file."))
            return

        # self.order(u"레이어를 선택하고 [지오패키지 읽기 시작] 버튼을 눌러주세요.")
        self.order(self.tr("Select the layer and press the [Read GeoPackage] button."))
        self.btnStart.setEnabled(True)

        self.writeConfig()

    def _on_click_btnStart(self):
        self.runImport()

    def _on_click_btnStop(self):
        self.stopProcessing()

    def runImport(self):
        try:
            self.isOnProcessing = True

            self.edtSrcFile.setEnabled(False)
            self.edtTgtFile.setEnabled(False)
            self.btnSrcFile.setEnabled(False)
            self.btnTgtFile.setEnabled(False)
            self.btnStop.setEnabled(True)
            self.btnStart.setEnabled(False)

            selectedRasterLayerList = list()
            selectedVectorLayerList = list()
            self.getSelectedLayerList(selectedRasterLayerList, selectedVectorLayerList)
            if len(selectedRasterLayerList) + len(selectedVectorLayerList) == 0:
                # self.error(u"선택된 레이어가 하나도 없어 진행할 수 없습니다.")
                self.error(self.tr("You can not proceed because there are no selected layers."))
                raise Exception()

            if self.readMode == "PDF":
                if not os.path.exists(self.pdfPath):
                    # raise Exception(u"선택한 온맵(PDF) 파일이 존재하지 않습니다.")
                    raise Exception(self.tr("The selected OnMap(PDF) file does not exist."))

                if not self.pdf:
                    rc = self.fillLayerTreeFromPdf()
                    if not rc:
                        # raise Exception(u"온맵(PDF) 파일에서 지리정보를 찾지 못했습니다.")
                        raise Exception(self.tr("Geographic information was not found in the OnMap(PDF) file."))

                rc = self.createGeoPackage()
                if not rc:
                    # raise Exception(u"지오패키지(GPKG) 파일을 만들지 못했습니다.")
                    raise Exception(self.tr("Failed to create GeoPackage(GPKG) file."))

                self.importPdfVector(selectedVectorLayerList)
                if self.forceStop:
                    raise StoppedByUserException()

                try:
                    # selectedRasterLayerList.index(u"영상")
                    selectedRasterLayerList.index(self.tr("PHOTO"))
                except ValueError:
                    pass
                else:
                    self.importPdfRaster()

            if self.forceStop:
                raise StoppedByUserException()

            self.openGeoPackage(selectedRasterLayerList, selectedVectorLayerList)

            if self.forceStop:
                raise StoppedByUserException()

            canvas = self.iface.mapCanvas()
            canvas.setExtent(canvas.mapSettings().fullExtent())
            canvas.refresh()
            # self.info(u"온맵 불러오기 성공!")
            self.info(self.tr("Importing OnMap succeeded!"))

            self.isOnProcessing = False
            self.close()

        except StoppedByUserException:
            pass
        except Exception as e:
            self.error(unicode(e))
        finally:
            QgsApplication.restoreOverrideCursor()
            self.isOnProcessing = False

            self.edtSrcFile.setEnabled(True)
            self.edtTgtFile.setEnabled(True)
            self.btnSrcFile.setEnabled(True)
            self.btnTgtFile.setEnabled(True)
            self.btnStop.setEnabled(False)
            self.btnStart.setEnabled(False)

    # 실제 동작중 이벤트가 오지 않는 문제가 있어 개발 중지
    def stopProcessing(self):
        if not self.isOnProcessing:
            return False

        # rc = QMessageBox.question(self, u"작업 강제 중지",
        #                           u"현재 작업을 강제로 중지하시겠습니까?\n\n"
        #                           u"작업 중지는 오류의 원인이 될 수도 있습니다.",
        #                           QMessageBox.Yes | QMessageBox.No)
        rc = QMessageBox.question(self, self.tr("Forcibly stop work"),
                                  self.tr("Are you sure want to force the current task to stop?\n\n"
                                  "Forcibly stop can also cause errors."),
                                  QMessageBox.Yes | QMessageBox.No)
        if rc != QMessageBox.Yes:
            return False

        self.forceStop = True

        self.edtSrcFile.setEnabled(True)
        self.edtTgtFile.setEnabled(True)
        self.btnSrcFile.setEnabled(True)
        self.btnTgtFile.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.btnStart.setEnabled(True)

        return True

    def closeEvent(self, event):
        if self.isOnProcessing:
            rc = self.stopProcessing()
            event.ignore()
        else:
            self.writeConfig()
            event.accept()

    def writeConfig(self):
        conf = ConfigParser.SafeConfigParser()
        conf.add_section('LastFile')
        conf.set("LastFile", "pdf", self.pdfPath)
        conf.set("LastFile", "gpkg", self.gpkgPath)
        # fp = codecs.open(self.configFile, "w", "UTF-8")
        fp = open(self.configFile, "w")
        conf.write(fp)
        fp.close()

    def readConfig(self):
        try:
            conf = ConfigParser.SafeConfigParser()
            conf.read(self.configFile)
            try:
                self.pdfPath = conf.get("LastFile", "pdf")
            except ConfigParser.NoSectionError:
                self.pdfPath = os.path.expanduser("~")
            try:
                self.gpkgPath = conf.get("LastFile", "gpkg")
            except ConfigParser.NoSectionError:
                self.gpkgPath = os.path.expanduser("~")
        except Exception as e:
            self.error(unicode(e))

    def fillLayerTreeFromPdf(self):
        QgsApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            self.pdfPath = self.edtSrcFile.text()
            rc =  self.getPdfInformation()
            if not rc:
                # self.error(u"PDF 파일에서 정보를 추출하지 못했습니다. 온맵 PDF가 아닌 듯 합니다.")
                self.error(self.tr("Failed to extract information from PDF file. It does not seem to be an on-map PDF."))
                raise Exception()

            self.treeLayer.clear()
            parentList = dict()
            parentList[0] = self.treeLayer
            # 영상 추가
            # item = addTreeItem(parentList[0], u"영상")
            item = addTreeItem(parentList[0], self.tr("PHOTO"))
            # item.layerName = u"영상"
            item.layerName = self.tr("PHOTO")
            item.layerId = -1

            titleList = dict()
            titleList[0] = "ROOT"
            for layerInfo in self.layerInfoList:
                name = layerInfo["name"]
                layerId = layerInfo["id"]
                if not LAYER_FILTER.match(name):
                    continue
                nameList = name.split("_")
                for i in range(len(nameList)):
                    title = nameList[i]
                    if not titleList.has_key(i+1):
                        level = i+1
                        titleList[level] = title
                        item = addTreeItem(parentList[level-1], title)
                        item.layerName = name
                        item.layerId = layerId
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
                        item.layerName = name
                        item.layerId = layerId
                        parentList[level] = item
                        if level <= 2:
                            item.setExpanded(True)
                        else:
                            item.setExpanded(False)
        except:
            return False
        finally:
            QgsApplication.restoreOverrideCursor()

        return True

    # TODO: GPKG 읽게 구현 필요
    def fillLayerTreeFromGpkg(self):
        QgsApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            self.gpkgPath = self.edtTgtFile.text()
            self.treeLayer.clear()

            rc =  self.getGpkgInformation()
            if not rc:
                # self.error(u"GPKG 파일에서 정보를 추출하지 못했습니다.")
                self.error(self.tr("Failed to extract information from GPKG file."))
                raise Exception()

            parentList = dict()
            parentList[0] = self.treeLayer

            titleList = dict()
            titleList[0] = "ROOT"
            for layerInfo in self.gpkglayerInfoList:
                name = layerInfo["name"]
                layerId = layerInfo["id"]
                nameList = name.split("_")
                for i in range(len(nameList)):
                    title = nameList[i]
                    if not titleList.has_key(i + 1):
                        level = i + 1
                        titleList[level] = title
                        item = addTreeItem(parentList[level - 1], title)
                        item.layerName = name
                        item.layerId = layerId
                        parentList[level] = item
                        if level <= 2:
                            item.setExpanded(True)
                        else:
                            item.setExpanded(False)
                    elif titleList[i + 1] != title:
                        level = i + 1
                        for j in range(level, len(titleList)):
                            titleList.pop(j)
                            parentList.pop(j)
                        titleList[level] = title
                        item = addTreeItem(parentList[level - 1], title)
                        item.layerName = name
                        item.layerId = layerId
                        parentList[level] = item
                        if level <= 2:
                            item.setExpanded(True)
                        else:
                            item.setExpanded(False)
        except:
            return False
        finally:
            QgsApplication.restoreOverrideCursor()

        return True

    def getPdfInformation(self):
        self.progressMainWork.setMinimum(0)
        self.progressMainWork.setMaximum(0)
        # self.lblMainWork.setText(u"선택한 온맵 파일 분석중...")
        self.lblMainWork.setText(self.tr("Analyzing selected OnMap file..."))
        # self.info(u"PDF 파일에서 정보추출 시작...")
        self.info(self.tr("Start extracting information from PDF files..."))
        force_gui_update()

        mapNo = findMapNo(os.path.basename(self.pdfPath))
        if mapNo is None:
            return

        try:
            boxLL, boxLR, boxTL, boxTR = mapNoToMapBox(mapNo)
        except NotImplementedError as e:
            self.error(repr(e))
        except:
            # self.error(u"해석할 수 없는 도엽명이어서 중단됩니다.")
            self.error(self.tr("The map name can not be interpreted, so it will stop."))
            return

        # get the driver
        srcDriver = ogr.GetDriverByName("PDF")

        # opening the PDF
        try:
            pdf = srcDriver.Open(self.pdfPath, 0)
        except Exception, e:
            self.error(unicode(e))
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

        # p = Proj(init="epsg:{}".format(crsId))
        # tmBoxLL = p(boxLL[0], boxLL[1])
        # tmBoxLR = p(boxLR[0], boxLR[1])
        # tmBoxTL = p(boxTL[0], boxTL[1])
        # tmBoxTR = p(boxTR[0], boxTR[1])

        fromCrs = osr.SpatialReference()
        fromCrs.ImportFromEPSG(4326)
        toCrs = osr.SpatialReference()
        toCrs.ImportFromEPSG(crsId)
        p = osr.CoordinateTransformation(fromCrs, toCrs)
        tmBoxLL = p.TransformPoint(boxLL[0], boxLL[1])
        tmBoxLR = p.TransformPoint(boxLR[0], boxLR[1])
        tmBoxTL = p.TransformPoint(boxTL[0], boxTL[1])
        tmBoxTR = p.TransformPoint(boxTR[0], boxTR[1])

        # use OGR specific exceptions
        # list to store layers'names
        layerInfoList = list()

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
                    self.error(u"[Unknown Type] " + ogr.GeometryTypeToName(geomType))

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

        self.debug(unicode((boxLL, boxLR, boxTL, boxTR)))

        affineTransform, _ = calcAffineTranform(boxLL, boxLR, boxTL, boxTR, tmBoxLL, tmBoxLR, tmBoxTL, tmBoxTR)

        srcList = [[imgLL[0], imgLL[1]], [imgLR[0], imgLR[1]], [imgTL[0], imgTL[1]], [imgTR[0], imgTR[1]]]
        srcNpArray = np.array(srcList, dtype=np.float32)
        tgtNpArray = affineTransform(srcNpArray)

        # self.info(u"정보추출 완료.")
        self.info(self.tr("Information extraction completed."))
        # self.lblMainWork.setText(u"작업 대기중")
        self.lblMainWork.setText(self.tr("Waiting for work"))
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

    def getGpkgInformation(self):
        self.progressMainWork.setMinimum(0)
        self.progressMainWork.setMaximum(0)
        # self.lblMainWork.setText(u"선택한 지오패키지 파일 분석중...")
        self.lblMainWork.setText(self.tr("Analyzing the selected GeoPackage file..."))
        # self.info(u"GPKG 파일에서 정보추출 시작...")
        self.info(self.tr("Start extracting information from GPKG file..."))
        force_gui_update()

        rc = False
        self.gpkglayerInfoList = list()

        try:
            gpkg = None
            gpkg = gdal.OpenEx(self.gpkgPath)
            if not gpkg:
                # raise Exception(u"지오패키지 열기 오류")
                raise Exception(self.tr("Open GeoPackage Error"))

            # 영상이 있는지 확인
            resSet = gpkg.ExecuteSQL("SELECT table_name from gpkg_contents where data_type = 'tiles'")
            for iObj in range(resSet.GetFeatureCount()):
                obj = resSet.GetFeature(iObj)
                rasterLayerName = obj.GetFieldAsString(0).decode('utf-8')
                self.gpkglayerInfoList.append({'id': -iObj-1, 'name': rasterLayerName})

            # id가 음수면 래스터, 0 이상이면 벡터
            resSet = gpkg.ExecuteSQL("SELECT table_name from gpkg_contents where data_type = 'features'")
            for iObj in range(resSet.GetFeatureCount()):
                obj = resSet.GetFeature(iObj)
                rasterLayerName = obj.GetFieldAsString(0).decode('utf-8')
                self.gpkglayerInfoList.append({'id': iObj, 'name': rasterLayerName})

            rc = True

        except Exception as e:
            self.error(e)
            rc = False

        self.progressMainWork.setMinimum(0)
        self.progressMainWork.setMaximum(100)
        self.progressMainWork.setValue(0)
        # self.lblMainWork.setText(u"지오패키지 정보추출 완료")
        self.lblMainWork.setText(self.tr("GeoPackage information extraction complete"))
        if rc:
            # self.info(u"지오패키지 정보추출 완료")
            self.info(self.tr("GeoPackage information extraction complete"))

        return rc

    def getSelectedLayerList(self, selectedRasterList, selectedVectorList, root = None):
        if not root:
            root = self.treeLayer.invisibleRootItem()
        signal_count = root.childCount()

        for i in range(signal_count):
            item = root.child(i)
            if item.checkState(0) == Qt.Checked:
                if item.childCount() == 0:
                    layerName = item.layerName
                    layerId = item.layerId
                    if layerId < 0:
                        selectedRasterList.append(layerName)
                    else:
                        selectedVectorList.append(layerName)
            if item.childCount() > 0:
                self.getSelectedLayerList(selectedRasterList, selectedVectorList, item)

        return

    def createGeoPackage(self):
        gpkg = None

        try:
            if os.path.isfile(self.gpkgPath):
                os.remove(self.gpkgPath)
        except Exception, e:
            # self.error(u"{} 파일을 다시 만들 수 없습니다. 아마 사용중인 듯 합니다.".format(self.gpkgPath))
            self.error(self.tr(u"Unable to recreate {} file. Maybe you are using it.")).format(self.gpkgPath)
            return

        driver = ogr.GetDriverByName("GPKG")
        # opening the FileGDB
        try:
            gpkg = driver.CreateDataSource(self.gpkgPath)
        except Exception, e:
            self.error(unicode(e))
            return

        self.gpkg = gpkg
        return True

    def importPdfVector(self, selectedLayerList):
        QgsApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # self.info (u"PDF에서 벡터정보 추출 시작...")
            self.info (self.tr("Start extracting vector information from PDF..."))
            createdLayerName = []

            # 좌표계 정보 생성
            crs = osr.SpatialReference()
            crs.ImportFromEPSG(self.crsId)

            # Create QGIS Layer
            totalCount = len(self.layerInfoList)
            crrIndex = 0
            self.progressMainWork.setMinimum(0)
            self.progressMainWork.setMaximum(totalCount)
            for layerInfo in self.layerInfoList:
                vPointLayer = None
                vLineLayer = None
                vPolygonLayer = None
                layerName = layerInfo["name"]

                crrIndex += 1
                self.progressMainWork.setValue(crrIndex)
                # self.lblMainWork.setText(u"{} 레이어 처리중({}/{})...".format(layerName, crrIndex, totalCount))
                self.lblMainWork.setText(self.tr(u"Processing {} layer({}/{})...").format(layerName, crrIndex, totalCount))

                # 선택된 레이어만 가져오기
                try:
                    index = selectedLayerList.index(layerName)
                except ValueError:
                    self.debug(u"Skipped Layer: {}".format(layerName))
                    continue

                self.debug(u"Processing Layer: {}".format(layerName))

                pdfLayer = self.pdf.GetLayerByIndex(layerInfo["id"])
                totalFeature = pdfLayer.GetFeatureCount()
                crrFeatureIndex = 0
                self.progressSubWork.setMinimum(0)
                self.progressSubWork.setMaximum(100)
                oldPct = -1
                for ogrFeature in pdfLayer:
                    crrFeatureIndex += 1
                    crrPct = int(crrFeatureIndex * 100 / totalFeature)
                    if crrPct != oldPct:
                        oldPct = crrPct
                        self.progressSubWork.setValue(crrPct)
                        # self.lblSubWork.setText(u"객체 추출중 ({}/{})...".format(crrFeatureIndex, totalFeature))
                        self.lblSubWork.setText(self.tr(u"Extracting object ({}/{})...").format(crrFeatureIndex, totalFeature))
                    force_gui_update()

                    if self.forceStop:
                        raise StoppedByUserException()

                    geometry = ogrFeature.GetGeometryRef()
                    fid = ogrFeature.GetFID()
                    geomType = geometry.GetGeometryType()

                    if geomType == ogr.wkbPoint or geomType == ogr.wkbMultiPoint:
                        if not vPointLayer:
                            outLayerName = u"{}_Point".format(layerName)
                            vPointLayer = self.gpkg.CreateLayer(outLayerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiPoint)
                            field = ogr.FieldDefn("GID", ogr.OFTInteger)
                            vPointLayer.CreateField(field)
                            createdLayerName.append(outLayerName)
                            self.debug(u"layerName:" + layerName)
                            self.debug(u"outLayerName:" + outLayerName)
                        vLayer = vPointLayer
                    elif geomType == ogr.wkbLineString or geomType == ogr.wkbMultiLineString:
                        if not vLineLayer:
                            outLayerName = u"{}_Line".format(layerName)
                            vLineLayer = self.gpkg.CreateLayer(outLayerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiLineString)
                            field = ogr.FieldDefn("GID", ogr.OFTInteger)
                            vLineLayer.CreateField(field)
                            createdLayerName.append(outLayerName)
                            self.debug(u"layerName:" + layerName)
                            self.debug(u"outLayerName:" + outLayerName)
                        vLayer = vLineLayer
                    elif geomType == ogr.wkbPolygon or geomType == ogr.wkbMultiPolygon:
                        if not vPolygonLayer:
                            outLayerName = u"{}_Polygon".format(layerName)
                            vPolygonLayer = self.gpkg.CreateLayer(outLayerName.encode('utf-8'), crs, geom_type=ogr.wkbMultiPolygon)
                            field = ogr.FieldDefn("GID", ogr.OFTInteger)
                            vPolygonLayer.CreateField(field)
                            createdLayerName.append(outLayerName)
                            self.debug(u"layerName:" + layerName)
                            self.debug(u"outLayerName:" + outLayerName)
                        vLayer = vPolygonLayer
                    else:
                        self.error(u"[ERROR] Unknown geometry type: " + geometry.GetGeometryName())
                        continue

                    featureDefn = vLayer.GetLayerDefn()
                    feature = ogr.Feature(featureDefn)
                    feature.SetField("GID", fid)

                    # collect vertex
                    self._TransformGeom(geometry)
                    feature.SetGeometry(geometry)
                    vLayer.CreateFeature(feature)

                    feature = None

            # self.info(u"벡터 가져오기 완료")
            self.info(self.tr("Vector import complete"))
        except StoppedByUserException:
            # self.error(u"사용자에 의해 중지됨")
            self.error(self.tr("Suspended by user"))
            QgsApplication.restoreOverrideCursor()
            return False
        except Exception as e:
            self.error(e)
            # self.error(u"벡터 가져오기 실패")
            self.error(self.tr("Vector import failed"))
            QgsApplication.restoreOverrideCursor()
            return False

        QgsApplication.restoreOverrideCursor()
        return True


    def _TransformGeom(self, geometry):
        if geometry.GetGeometryCount() == 0:
            pointList = geometry.GetPoints()
            srcNpArray = np.array(pointList, dtype=np.float32)

            # transform all vertex
            tgtNpList = self.affineTransform(srcNpArray)

            # move vertex
            for i in range(0, len(srcNpArray)):
                geometry.SetPoint(i, tgtNpList[i][0], tgtNpList[i][1])
        else:
            for geomId in range(geometry.GetGeometryCount()):
                subGeom = geometry.GetGeometryRef(geomId)
                self._TransformGeom(subGeom)


    def importPdfRaster(self):
        QgsApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # self.info(u"영상 정보 추출시작")
            self.info(self.tr("Start extracting photo information"))
            self.progressMainWork.setMinimum(0)
            self.progressMainWork.setMaximum(4)

            fh = open(self.pdfPath, "rb")
            pdfObj = PyPDF2.PdfFileReader(fh)

            pageObj = pdfObj.getPage(0)

            try:
                xObject = pageObj['/Resources']['/XObject'].getObject()
            except KeyError:
                # raise Exception(u"영상 레이어가 없어 가져올 수 없습니다.")
                raise Exception(self.tr("Can not import because there is no photo layer."))

            self.progressMainWork.setValue(1)
            # self.lblMainWork.setText(u"영상 조각 추출중...")
            self.lblMainWork.setText(self.tr("Extracting photo fragments..."))
            if self.forceStop:
                raise StoppedByUserException()

            images = {}
            totalCount = len(xObject)
            self.progressSubWork.setMinimum(0)
            self.progressSubWork.setMaximum(totalCount)
            crrIndex = 0

            for obj in xObject:
                crrIndex += 1
                self.progressSubWork.setValue(crrIndex)
                # self.lblSubWork.setText(u"영상 조각 처리중({}/{})...".format(crrIndex, totalCount))
                self.lblSubWork.setText(self.tr("Photo fragments processing({}/{})...").format(crrIndex, totalCount))
                force_gui_update()
                if self.forceStop:
                    raise StoppedByUserException()

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
            # self.info(u"영상 병합 시작")
            self.info(self.tr("Start merging photo"))
            self.progressMainWork.setValue(2)
            # self.lblMainWork.setText(u"영상 병합중...")
            self.lblMainWork.setText(self.tr("Merging photo fragments..."))
            if self.forceStop:
                raise StoppedByUserException()

            keys = images.keys()
            keys.sort()

            totalCount = len(keys)
            self.progressSubWork.setMinimum(0)
            self.progressSubWork.setMaximum(totalCount)

            mergedWidth = None
            mergedHeight = None
            mergedMode = None
            crrIndex = 0
            for key in keys:
                crrIndex += 1
                self.progressSubWork.setValue(crrIndex)
                # self.lblSubWork.setText(u"영상 조각 처리중({}/{})...".format(crrIndex, totalCount))
                self.lblSubWork.setText(self.tr("Processing photo fragments({}/{})...").format(crrIndex, totalCount))
                force_gui_update()
                if self.forceStop:
                    raise StoppedByUserException()

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

            # self.info(u"병합된 영상을 지오패키지에 저장 시작")
            self.info(self.tr("Start saving merged photo into GeoPackage"))
            self.progressMainWork.setValue(3)
            # self.lblMainWork.setText(u"병합된 영상 저장중...")
            self.lblMainWork.setText(self.tr("Saving merged photo..."))
            if self.forceStop:
                raise StoppedByUserException()

            self.progressSubWork.setMinimum(0)
            self.progressSubWork.setMaximum(5)
            self.progressSubWork.setValue(0)
            # self.lblSubWork.setText(u"영상 저장중...")
            self.lblSubWork.setText(self.tr("Saving photo..."))
            if self.forceStop:
                raise StoppedByUserException()

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
                # options=["APPEND_SUBDATASET=YES", u"RASTER_TABLE=영상", "TILE_FORMAT=JPEG"]
                options=["APPEND_SUBDATASET=YES", self.tr("RASTER_TABLE=PHOTO"), "TILE_FORMAT=JPEG"]
            )

            dataset.SetProjection(crs_wkt)
            xScale = math.sqrt(matrix[0][0] ** 2 + matrix[1][0] ** 2)
            yScale = math.sqrt(matrix[0][1] ** 2 + matrix[1][1] ** 2)
            dataset.SetGeoTransform((matrix[0][2], xScale, 0.0, matrix[1][2], 0.0, -yScale))

            self.progressSubWork.setValue(1)
            force_gui_update()
            if self.forceStop:
                raise StoppedByUserException()

            # TODO: 이 다음 부분에서 메모리 오류가 있다.
            band1 = np.array(list(mergedImage.getdata(0))).reshape(-1, mergedWidth)
            self.progressSubWork.setValue(2)
            force_gui_update()
            if self.forceStop:
                raise StoppedByUserException()
            band2 = np.array(list(mergedImage.getdata(1))).reshape(-1, mergedWidth)
            self.progressSubWork.setValue(3)
            force_gui_update()
            if self.forceStop:
                raise StoppedByUserException()
            band3 = np.array(list(mergedImage.getdata(2))).reshape(-1, mergedWidth)
            self.progressSubWork.setValue(4)
            force_gui_update()
            if self.forceStop:
                raise StoppedByUserException()

            dataset.GetRasterBand(1).WriteArray(band1)
            dataset.GetRasterBand(2).WriteArray(band2)
            dataset.GetRasterBand(3).WriteArray(band3)
            dataset.FlushCache()
            # dataset.ReleaseResultSet(dataset)

            self.progressSubWork.setValue(5)
            force_gui_update()
            if self.forceStop:
                raise StoppedByUserException()

            mergedImage.close()
            del mergedImage
            del band1
            del band2
            del band3
            del dataset
            self.progressMainWork.setValue(4)
            force_gui_update()

        except StoppedByUserException:
            QgsApplication.restoreOverrideCursor()
            # self.error(u"사용자에 의해 중지됨")
            self.error(self.tr("Suspended by user"))
            return False
        except Exception as e:
            self.error(e)
            QgsApplication.restoreOverrideCursor()
            # self.error(u"영상 가져오기 실패")
            self.error(self.tr("Photo import failed"))
            return False

        QgsApplication.restoreOverrideCursor()
        # self.lblMainWork.setText(u"영상 처리 완료")
        self.lblMainWork.setText(self.tr("Photo processing completed"))
        # self.info(u"영상 가져오기 완료")
        self.info(self.tr("Photo import completed"))
        return True

    def openGeoPackage(self, selectedRasterLayerList, selectedVectorLayerList):
        QgsApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            if self.readMode == "PDF":
                # 래스터 로딩
                try:
                    # selectedRasterLayerList.index(u"영상")
                    selectedRasterLayerList.index(self.tr("PHOTO"))
                    try:
                        # layer = self.iface.addRasterLayer(self.gpkgPath, u"영상", "gdal")
                        layer = self.iface.addRasterLayer(self.gpkgPath, self.tr("PHOTO"), "gdal")
                    except:
                        layer = None
                    if not layer:
                        # self.error(u"영상 레이어 읽기 실패")
                        self.error(self.tr("Photo layer load failed"))
                except ValueError:
                    pass

                # 벡터 로딩
                gpkg = None
                try:
                    gpkg = ogr.Open(self.gpkgPath)
                    if not gpkg:
                        raise Exception()

                    numLayer = gpkg.GetLayerCount()
                    iLayer = 0
                    self.progressMainWork.setMinimum(0)
                    self.progressMainWork.setMaximum(numLayer)
                    # self.lblMainWork.setText(u"변환된 지오패키지 읽는 중...")
                    self.lblMainWork.setText(self.tr("Loading the converted GeoPackage..."))
                    # self.info(u"지오패키지 불러오기 시작")
                    self.info(self.tr("Starting GeoPackage loading"))
                    self.progressSubWork.setMinimum(0)
                    self.progressSubWork.setMaximum(numLayer)

                    for layer in gpkg:
                        iLayer += 1
                        self.progressMainWork.setValue(iLayer)
                        self.progressSubWork.setValue(iLayer)
                        # self.lblSubWork.setText(u"벡터 레이어 읽는 중({}/{})...".format(iLayer, numLayer))
                        self.lblSubWork.setText(self.tr("Reading vector layer({}/{})...").format(iLayer, numLayer))
                        force_gui_update()
                        if self.forceStop:
                            raise StoppedByUserException()

                        layerName = unicode(layer.GetName().decode('utf-8'))
                        orgLayerName = layerName.strip("_Point").strip("_Line").strip("_Polygon")

                        try:
                            selectedVectorLayerList.index(orgLayerName)
                        except ValueError:
                            self.debug(u"SKIP: {}".format(layerName))
                            continue
                        self.debug(u"OPEN: {}".format(layerName))

                        try:
                            uri = u"{}|layername={}".format(self.gpkgPath, layerName)
                            layer = self.iface.addVectorLayer(uri, None, "ogr")
                            try:
                                layer.setName(layerName)
                            except:
                                layer.setLayerName(layerName)
                        except:
                            layer = None

                        if not layer:
                            # self.error(u"{} 레이어 읽기 실패".format(layerName))
                            self.error(self.tr(u"Failed to read {} layer").format(layerName))
                except Exception as e:
                    self.error(e)
                finally:
                    if gpkg:
                        del gpkg
            else: # self.readMode == "GPKG"
                numLayer = len(selectedRasterLayerList) + len(selectedVectorLayerList)
                self.progressMainWork.setMinimum(0)
                self.progressMainWork.setMaximum(numLayer)
                # self.lblMainWork.setText(u"기존 지오패키지 읽는 중...")
                self.lblMainWork.setText(self.tr("Loading existing GeoPackage..."))
                # self.info(u"지오패키지 불러오기 시작")
                self.info(self.tr("Starting GeoPackage import"))

                iLayer = 0
                self.progressSubWork.setMinimum(0)
                self.progressSubWork.setMaximum(numLayer)

                # 래스터 로딩
                for layerName in selectedRasterLayerList:
                    iLayer += 1
                    self.progressMainWork.setValue(iLayer)
                    self.progressSubWork.setValue(iLayer)
                    # self.lblSubWork.setText(u"레이어 읽는 중({}/{})...".format(iLayer, numLayer))
                    self.lblSubWork.setText(self.tr("Loading layer({}/{})...").format(iLayer, numLayer))
                    force_gui_update()
                    if self.forceStop:
                        raise StoppedByUserException()
                    try:
                        self.debug(layerName)
                        layer = self.iface.addRasterLayer(self.gpkgPath, layerName, "gdal")
                    except:
                        layer = None
                    if not layer:
                        # self.error(u"{} 레이어 읽기 실패".format(layerName))
                        self.error(self.tr(u"Failed to read {} layer").format(layerName))

                # 벡터 로딩
                for layerName in selectedVectorLayerList:
                    iLayer += 1
                    self.progressMainWork.setValue(iLayer)
                    self.progressSubWork.setValue(iLayer)
                    # self.lblSubWork.setText(u"레이어 읽는 중({}/{})...".format(iLayer, numLayer))
                    self.lblSubWork.setText(self.tr("Loading layer({}/{})...").format(iLayer, numLayer))
                    force_gui_update()
                    if self.forceStop:
                        raise StoppedByUserException()
                    try:
                        uri = u"{}|layername={}".format(self.gpkgPath, layerName)
                        layer = self.iface.addVectorLayer(uri, None, "ogr")
                        try:
                            layer.setName(layerName)
                        except:
                            layer.setLayerName(layerName)
                    except:
                        layer = None
                    if not layer:
                        # self.error(u"{} 레이어 읽기 실패".format(layerName))
                        self.error(self.tr(u"Failed to read {} layer").format(layerName))

        except StoppedByUserException:
            QgsApplication.restoreOverrideCursor()
            # self.error(u"사용자에 의해 중지됨")
            self.error(self.tr("Suspended by user"))
            return False
        except Exception as e:
            self.error(e)
            QgsApplication.restoreOverrideCursor()
            # self.error(u"영상 가져오기 실패")
            self.error(self.tr("Photo import failed"))
            return False

        QgsApplication.restoreOverrideCursor()
        # self.info(u"지오패키지 불러오기 완료")
        self.info(self.tr("GeoPackage import complete"))

        return True
