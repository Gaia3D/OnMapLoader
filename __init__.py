# -*- coding: utf-8 -*-
"""
/***************************************************************************
 OnMapLoader
                                 A QGIS plugin
 Tool for loading OnMap(Korea NGII PDF Map) to QGIS
                             -------------------
        begin                : 2017-09-08
        copyright            : (C) 2017 by BJ Jang / Gaia3D
        email                : jangbi882@gmail.com
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load OnMapLoader class from file OnMapLoader.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .onmap_loader import OnMapLoader
    return OnMapLoader(iface)
