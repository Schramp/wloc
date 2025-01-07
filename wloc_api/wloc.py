# -*- coding: utf-8 -*-
#!/usr/bin/python

# Mostly taken from paper by François-Xavier Aguessy and Côme Demoustier
# http://fxaguessy.fr/rapport-pfe-interception-ssl-analyse-donnees-localisation-smartphones/
# 
# Seperated from iSniff
# Forked from https://github.com/marcelmaatkamp/iSniff-GPS.git

import sys
import code
import requests
import wloc_api.BSSIDApple_pb2 as BSSIDApple_pb2
import wloc_api.GSM_pb2 as GSM_pb2

#import simplekml



def padBSSID(bssid):
    result = ''
    for e in bssid.split(':'):
        if len(e) == 1:
            e = '0%s' % e
        result += e + ':'
    return result.strip(':')


def ListWifiDepuisApple(wifi_list):
    apdict = {}
    #kml = simplekml.Kml()
    for wifi in wifi_list.wifi:
        #print "Wifi BSSID : ", wifi.bssid
        if wifi.HasField('location'):
            lat = wifi.location.latitude * pow(10, -8)
            lon = wifi.location.longitude * pow(10, -8)
            #kml.newpoint(name=wifi.bssid, coords=[(lon,lat)])
            mac = padBSSID(wifi.bssid)
            apdict[mac] = (lat, lon)
        if wifi_list.HasField('valeur_inconnue1'):
            print('Inconnu1 : ', '%X' % wifi_list.valeur_inconnue1)
        if wifi_list.HasField('valeur_inconnue2'):
            print('Inconnu2 : ', '%X' % wifi_list.valeur_inconnue1)
        if wifi_list.HasField('APIName'):
            print('APIName : ', wifi_list.APIName)
    #kml.save("test.kml")
    return apdict

class NetworkInfo:
    def __init__(self, mcc, mnc, lac, eci, latitude=None, longitude=None, accuracy=None):
        # Network information
        self._mcc = mcc        # Mobile Country Code
        self._mnc = mnc        # Mobile Network Code
        self._lac = lac        # Location Area Code
        self._eci = eci        # Evolved Cell Identity
        
        # Optional GPS location information
        self._latitude = latitude
        self._longitude = longitude
        self._accuracy = accuracy

    def get_all(self):
        allfields = {}
        allfields['mcc'] = self._mcc
        allfields['mnc'] = self._mnc
        allfields['lac'] = self._lac
        allfields['eci'] = self._eci
        allfields['lat'] = self._latitude
        allfields['lon'] = self._longitude
        allfields['accuracy'] = self._accuracy
        return allfields

    # Getters
    def get_mcc(self):
        return self._mcc

    def get_mnc(self):
        return self._mnc

    def get_lac(self):
        return self._lac

    def get_eci(self):
        return self._eci

    def get_location(self):
        # Return a tuple (latitude, longitude, accuracy)
        return (self._latitude, self._longitude, self._accuracy)

    # Setters
    def set_mcc(self, mcc):
        self._mcc = mcc

    def set_mnc(self, mnc):
        self._mnc = mnc

    def set_lac(self, lac):
        self._lac = lac

    def set_eci(self, eci):
        self._eci = eci

    def set_location(self, latitude=None, longitude=None, accuracy=None):
        self._latitude = latitude
        self._longitude = longitude
        self._accuracy = accuracy

    def cellidString(self):
        return '%s:%s:%s:%s' % (self._mcc, self._mnc, self._lac, self._eci)

    # Method to display all network information
    def display_info(self):
        info = f"MCC: {self._mcc}\nMNC: {self._mnc}\nLAC: {self._lac}\nECI: {self._eci}\n"
        if self._latitude is not None and self._longitude is not None:
            info += f"Location:  (Lat,Lon) ({self._latitude}, {self._longitude}), Accuracy: {self._accuracy} meters\n"
        else:
            info += "Location: Not available\n"
        return info

def ProcessMobileResponse(cell_list):
    celldict = {}
    #kml = simplekml.Kml()
    for cell in cell_list.cell:
        #print(cell)
        if cell.HasField(
                'location'
        ) and cell.CID != -1:  # exclude "LAC" type results (usually 20 in each response)
            lat = cell.location.latitude * pow(10, -8)
            lon = cell.location.longitude * pow(10, -8)

            value = NetworkInfo(cell.MCC, cell.MNC, cell.LAC, cell.CID, lat, lon, cell.location.confidence)

            cellid = value.cellidString()
            #kml.newpoint(name=cellid, coords=[(lon,lat)])
            cellname = 'MNC:%s LAC:%s CID:%s' % (cell.MNC, cell.LAC,
                                                     cell.CID)
            try:
                if cell.HasField('channel'):
                    cellname += ' Channel:%s' % cell.channel
            except ValueError:
                pass
            celldict[cellid] = value
        else:
            pass
            #print 'Weird cell: %s' % cell
        #kml.save("test.kml")
        #f=file('result.txt','w')
        #for (cid,desc) in celldesc.items():
        #print cid, desc
        #f.write('%s %s\n'%(cid,desc))
        #f.close()
        #print 'Wrote result.txt'
    return celldict


def QueryBSSID(query, more_results=True):
    liste_wifi = BSSIDApple_pb2.BlockBSSIDApple()
    if type(query) in (str, unicode):
        bssid_list = [query]
    elif type(query) == list:
        bssid_list = query
    else:
        raise TypeError(
            'Provide 1 BSSID as string or multiple BSSIDs as list of strings')
    for bssid in bssid_list:
        wifi = liste_wifi.wifi.add()
        wifi.bssid = bssid
    liste_wifi.valeur_inconnue1 = 0
    if more_results:
        liste_wifi.valeur_inconnue2 = 0  # last byte in request == 0 means return ~400 results, 1 means only return results for BSSIDs queried
    else:
        liste_wifi.valeur_inconnue2 = 1
    chaine_liste_wifi = liste_wifi.SerializeToString()
    longueur_chaine_liste_wifi = len(chaine_liste_wifi)
    headers = {'Content-Type':'application/x-www-form-urlencoded', 'Accept':'*/*', "Accept-Charset": "utf-8","Accept-Encoding": "gzip, deflate",\
      "Accept-Language":"en-us", 'User-Agent':'locationd/1753.17 CFNetwork/711.1.12 Darwin/14.0.0'}
    data = "\x00\x01\x00\x05" + "en_US" + "\x00\x13" + "com.apple.locationd" + "\x00\x0a" + "8.1.12B411" + "\x00\x00\x00\x01\x00\x00\x00" + chr(
        longueur_chaine_liste_wifi) + chaine_liste_wifi
    r = requests.post(
        'https://gs-loc.apple.com/clls/wloc',
        headers=headers,
        data=data,
        verify=False
    )  # CN of cert on this hostname is sometimes *.ls.apple.com / ls.apple.com, so have to disable SSL verify
    liste_wifi = BSSIDApple_pb2.BlockBSSIDApple()
    liste_wifi.ParseFromString(r.content[10:])
    return ListWifiDepuisApple(liste_wifi)


def QueryMobile(cellid, LTE=False):
    (MCC, MNC, LAC, CID) = map(int, cellid.split(':'))
    if LTE:
        req = GSM_pb2.CellReqToApple25(
        )  # Request type 25 -> Response type 22 (LTE?)
        req.cell.MCC = MCC
        req.cell.MNC = MNC
        req.cell.LAC = LAC
        req.cell.CID = CID
    else:
        req = GSM_pb2.CellReqToApple1(
        )  # Request 1 -> Response type 1 (GSM/3G?)
        cell = req.cell.add()
        cell.MCC = MCC
        cell.MNC = MNC
        cell.LAC = LAC
        cell.CID = CID
        #cell2 = req.cell.add() #505:2:33300:151564484
        #cell2.MCC = 505
        #cell2.MNC = 3
        #cell2.LAC = 334
        #cell2.CID = 87401254
        req.param3 = 0  # this affects whether you get cells or LAC areas
        req.param4 = 1  #
        req.ua = 'com.apple.Maps'

    req_string = req.SerializeToString()
    headers = {'Content-Type':'application/x-www-form-urlencoded', 'Accept':'*/*', "Accept-Charset": "utf-8","Accept-Encoding": "gzip, deflate",\
      "Accept-Language":"en-us", 'User-Agent':'locationd/1753.17 CFNetwork/711.1.12 Darwin/14.0.0'}
    data = b"\x00\x01\x00\x05" + b"en_US" + b"\x00\x13" + b"com.apple.locationd" + b"\x00\x0c" + b"7.0.3.11B511" + b"\x00\x00\x00\x01\x00\x00\x00" + chr(
        len(req_string)).encode("ASCII") + req_string
    #data = "\x00\x01\x00\x05"+"en_US"+"\x00\x13"+"com.apple.locationd"+"\x00\x0c"+"6.1.1.10B145"+"\x00\x00\x00\x01\x00\x00\x00"+chr(len(req_string)) + req_string;
    #f=file('request.bin','wb')
    #f.write(req_string)
    #print('Wrote request.bin')
    #f.close()
    cellid = '%s:%s:%s:%s' % (MCC, MNC, LAC, CID)
    if LTE:
        response = GSM_pb2.CellInfoFromApple22()
    else:
        response = GSM_pb2.CellInfoFromApple1()

    try:
        with open('cache/'+cellid+'.bin','rb') as f:
            content = f.read()
        response.ParseFromString(content[10:])
        return ProcessMobileResponse(response)
    except:
        pass

    r = requests.post(
        'https://gs-loc.apple.com/clls/wloc',
        headers=headers,
        data=data,
        verify=False
    )  #the remote SSL cert CN on this server doesn't match hostname anymore
    with open('cache/'+cellid+'.bin','wb') as f:
        f.write(r.content)
    # The first bytes seem not to be part of the protobuf (it decodes to field nr 0 wich is illegal)
    # 00000000  00 01 00 00 00 01 00 00  16 5a                    |.........Z|
    #                             ----------->  Big endian length
    #           |---------------->              Perhaps Versioning info?
    # Therefor skip the first 10 bytes
    response.ParseFromString(r.content[10:])
    return ProcessMobileResponse(response)
