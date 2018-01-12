# -*- coding: utf-8 -*-
"""
/***************************************************************************
 OnMapLoader
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
from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
from PyQt4.QtGui import QAction, QIcon
from PyQt4.QtGui import *


def tr(message):
    return QCoreApplication.translate('@default', message)

try:
    from PIL import Image
except:
    # raise Exception(u"죄송합니다. PIL 라이브러리가 없어 실행할 수 없습니다.\nhttp://www.kyngchaos.com/software/python 에서 PIL을 설치하실 수 있습니다.")
    raise Exception(tr(u"Sorry. Can not run this plugin because there is no PIL library.\nYou can install PIL from http://www.kyngchaos.com/software/python."))

# Import the code for the dialog
from onmap_loader_dialog import OnMapLoaderDialog
import os.path
import os
import webbrowser
from osgeo import gdal, ogr


class OnMapLoader:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.


        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        checkMsg = self.checkGdal()
        if checkMsg is not None:
            raise Exception(checkMsg.encode("UTF-8"))

        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'OnMapLoader_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)


        # Declare instance attributes
        self.actions = []
        # self.menu = self.tr(u'&OnMap Loader')
        self.menu = tr(u'&OnMap Loader')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'OnMapLoader')
        self.toolbar.setObjectName(u'OnMapLoader')

    def checkGdal(self):
        if gdal.VersionInfo() < "2000000":
            # return u"죄송합니다. GDAL 버전이 낮아 실행 불가능합니다.\nGDAL 2.0 이상이 필요합니다."
            return tr(u"Sorry. The GDAL version is low and can not run this plugin.\nGDAL 2.0 or higher is required.")
        if not ogr.GetDriverByName("PDF"):
            # msg = u"죄송합니다. 설치된 GDAL이 PDF를 지원하지 않아 실행 불가능합니다."
            msg = tr(u"Sorry. Can not run this plugin because installed GDAL not support PDF.")
            if os.name == "posix":
                # msg += u"\n다음 경로에서 GeoPDF Plugin을 받아 설치후 다시 실행해 주십시오."
                msg += tr(u"\nPlease acquire GeoPDF Plugin from the following path and install it again.")
                msg += u"\nhttp://www.kyngchaos.com/files/software/frameworks/GDAL-GeoPDF_Plugin-2.1.1-1.dmg"
            return msg
        if not ogr.GetDriverByName("GPKG"):
            # return u"죄송합니다. 설치된 GDAL이 GeoPackage를 지원하지 않아 실행 불가능합니다."
            return tr(u"Sorry. Can not run this plugin because installed GDAL not support GeoPackage.")
        return None


    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        return QCoreApplication.translate('OnMapLoader', message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = os.path.dirname(__file__) + "/icon.png"
        self.add_action(
            icon_path,
            # text=u'NGII 온맵(OnMap) 로더 ',
            text=self.tr('NGII OnMap Loader'),
            callback=self.run,
            parent=self.iface.mainWindow())
        icon_path = os.path.dirname(__file__) + "/help.png"
        self.add_action(
            icon_path,
            # text=u'도움말',
            text=self.tr('Help'),
            callback=self.help,
            parent=self.iface.mainWindow())

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                # self.tr(u'온맵 로더(&O)'),
                self.tr('&OnMap Loader'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    def run(self):
        """Run method that performs all the real work"""
        # show the dialog
        self._init_dialog()
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()
        # See if OK was pressed
        if result:
            # Do something useful here - delete the line containing pass and
            # substitute with your code.
            pass

    def help(self):
        webbrowser.open_new(u'https://gaia3d.github.io/OnMapLoader/')

    def _init_dialog(self):
        # Create the dialog (after translation) and keep reference
        self.dlg = OnMapLoaderDialog(self.iface, self.iface.mainWindow())

