WLOC Apple location lookup
==========================

Lookup location based on CellID end WIFI MAC Addresses.

Focus is on the CellID based download, and this has been taken from iSniff.
iSniff however was python2.7 thus the wloc.py is migrated to python3

Als the .proto files hase been extended based on observed protobuf responses

TODO: Seperate just the lookup part from the iSniff wrapping.



Dependencies
------------

See requirements.txt for python modules and versions required.

iSniff GPS was developed on a Ubuntu 12.04 (32-bit) VM with Python 2.7.3, Django 1.5.4 and Scapy 2.2.0-dev.
The web interface code has been updated and tested with Django 1.7.1 running on Mac OS X Yosemite with Python 2.7.8.
Network sniffing has not been tested on Mac OS X.

Credits
-------

Forked from https://github.com/marcelmaatkamp/iSniff-GPS.git

Based on iSniff GPS
Written by @hubert3 / hubert(at)pentest.com. Presented at Blackhat USA July 2012, code published on Github 2012-08-31.
Within iSniff the protobuf files for both sources have been described 

The implementation of wloc.py is based on work by François-Xavier Aguessy and Côme Demoustier [[2]][paper].

Mark Wuergler of Immunity, Inc. provided helpful information through mailing list posts and Twitter replies.

Includes Bluff JS chart library by James Coglan.

1. http://arstechnica.com/apple/2012/03/anatomy-of-an-iphone-leak/
2. http://fxaguessy.fr/rapport-pfe-interception-ssl-analyse-donnees-localisation-smartphones/

[ars]: http://arstechnica.com/apple/2012/03/anatomy-of-an-iphone-leak/
[paper]: http://fxaguessy.fr/rapport-pfe-interception-ssl-analyse-donnees-localisation-smartphones/
