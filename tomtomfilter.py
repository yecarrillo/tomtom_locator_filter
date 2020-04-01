# -*- coding: utf-8 -*-

from qgis.core import Qgis, QgsMessageLog, QgsLocatorFilter, QgsLocatorResult, QgsRectangle, \
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

from . networkaccessmanager import NetworkAccessManager, RequestsException

from qgis.PyQt.QtCore import pyqtSignal

import json


class TomTomFilterPlugin:

    def __init__(self, iface):

        self.iface = iface

        self.filter = TomTomLocatorFilter(self.iface)

        # THIS is not working?? As in show_problem never called
        self.filter.resultProblem.connect(self.show_problem)
        self.iface.registerLocatorFilter(self.filter)

    def show_problem(self, err):
        self.filter.info("showing problem???")  # never come here?
        self.iface.messageBar().pushWarning("TomTomLocatorFilter Error", '{}'.format(err))

    def initGui(self):
        pass

    def unload(self):
        self.iface.deregisterLocatorFilter(self.filter)
        #self.filter.resultProblem.disconnect(self.show_problem)


# SEE: https://github.com/qgis/QGIS/blob/master/src/core/locator/qgslocatorfilter.h
#      for all attributes/members/functions to be implemented
class TomTomLocatorFilter(QgsLocatorFilter):


    SEARCH_URL = 'https://api.tomtom.com/search/2/search/'
    # test url to be able to force errors
    #SEARCH_URL = 'http://duif.net/cgi-bin/qlocatorcheck.cgi?q='

    # some magic numbers to be able to zoom to more or less defined levels
    ADDRESS = 1000
    STREET = 1500
    ZIP = 3000
    PLACE = 30000
    CITY = 120000
    ISLAND = 250000
    COUNTRY = 4000000

    resultProblem = pyqtSignal(str)

    def __init__(self, iface):
        # you REALLY REALLY have to save the handle to iface, else segfaults!!
        self.iface = iface
        super(QgsLocatorFilter, self).__init__()

    def name(self):
        return self.__class__.__name__

    def clone(self):
        return TomTomLocatorFilter(self.iface)

    def displayName(self):
        return 'TomTom Geocoder (end with space to search)'

    def prefix(self):
        return 'tomtom'

    def fetchResults(self, search, context, feedback):

        if len(search) < 2:
            return

        # End with a space to trigger a search:
        if search[-1] != ' ':
            return

        url = '{}{}'.format(self.SEARCH_URL, search)
        url = url + '.json?'
        url = url + '&key='
        url = url + '&idxSet=POI,Geo,Addr,PAD,Str,Xstr'
        self.info('Search url {}'.format(url))
        nam = NetworkAccessManager()
        try:
            # use BLOCKING request, as fetchResults already has it's own thread!
            (response, content) = nam.request(url, blocking=True)
            #self.info(response)
            #self.info(response.status_code)
            if response.status_code == 200:  # other codes are handled by NetworkAccessManager
                content_string = content.decode('utf-8')
                locations = json.loads(content_string)
                for loc in locations['results']:
                    result = QgsLocatorResult()
                    result.filter = self
                    if loc['type'] == 'Geography':
                        loc_type = loc['entityType']
                    else:
                        loc_type = loc['type']

                    if loc['type'] == 'Geography':
                        loc_display = loc['address']['freeformAddress'] + ', ' + loc['address']['country']
                    elif loc['type'] == 'Street' or loc['type'] == 'Cross Street':
                        loc_display = loc['address']['streetName'] + ', ' + loc['address']['municipality'] + ', ' + loc['address']['country']
                    elif loc['type'] == 'POI':
                        if loc['poi'].get('brands'):
                            loc_display = loc['poi']['brands'][0]['name'] + ' ' + loc['poi']['name'] + ' - ' + loc['address']['municipality'] + ', ' + loc['address']['country']
                        else:
                            loc_display = loc['poi']['name'] + ' - ' + loc['address']['municipality'] + ', ' + loc['address']['country']
                    else:
                        loc_display = loc['address']['freeformAddress'] + ', ' + loc['address']['country']

                    result.displayString = '{} ({})'.format(loc_display, loc_type)
                    # use the json full item as userData, so all info is in it:
                    result.userData = loc
                    self.resultFetched.emit(result)

        except RequestsException as err:
            # Handle exception..
            # only this one seems to work
            self.info(err)
            # THIS: results in a floating window with a warning in it, wrong thread/parent?
            #self.iface.messageBar().pushWarning("TomTomLocatorFilter Error", '{}'.format(err))
            # THIS: emitting the signal here does not work either?
            self.resultProblem.emit('{}'.format(err))


    def triggerResult(self, result):
        self.info("UserClick: {}".format(result.displayString))
        doc = result.userData
        if doc['type'] == 'Street' or doc['type'] == 'POI' or doc['type'] == 'Cross Street' or doc['type'] == 'Point Address' \
                or doc['type'] == 'Address Range':
            extent = doc['viewport']
        else:
            extent = doc['boundingBox']

        # "boundingbox": ["52.641015", "52.641115", "5.6737302", "5.6738302"]
        rect = QgsRectangle(float(extent['topLeftPoint']['lon']), float(extent['btmRightPoint']['lat']), float(extent['btmRightPoint']['lon']), float(extent['topLeftPoint']['lat']))
        dest_crs = QgsProject.instance().crs()
        results_crs = QgsCoordinateReferenceSystem(4326, QgsCoordinateReferenceSystem.PostgisCrsId)
        transform = QgsCoordinateTransform(results_crs, dest_crs, QgsProject.instance())
        r = transform.transformBoundingBox(rect)
        self.iface.mapCanvas().setExtent(r, False)
        # sometimes TomTom has result with very tiny boundingboxes, let's set a minimum
        if self.iface.mapCanvas().scale() < 500:
            self.iface.mapCanvas().zoomScale(500)
        self.iface.mapCanvas().refresh()

    def info(self, msg=""):
        QgsMessageLog.logMessage('{} {}'.format(self.__class__.__name__, msg), 'TomTomLocatorFilter', Qgis.Info)
