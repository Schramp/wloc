WLOC Apple location lookup
==========================

Lookup location based on CellID end WIFI MAC Addresses.

Focus is on the CellID based download, and this has been taken from iSniff.
iSniff however was python2.7 thus the wloc.py is migrated to python3

Als the .proto files hase been extended based on observed protobuf responses



Dependencies
------------

See requirements.txt for python modules and versions required.

Credits
-------
Based on iSniff GPS (Forked from https://github.com/marcelmaatkamp/iSniff-GPS.git)


Written by @hubert3 / hubert(at)pentest.com. Presented at Blackhat USA July 2012, code published on Github 2012-08-31.
Within iSniff the protobuf files for both sources have been described 

The implementation of wloc.py is based on work by François-Xavier Aguessy and Côme Demoustier [[2]][paper].

Mark Wuergler of Immunity, Inc. provided helpful information through mailing list posts and Twitter replies.

Includes Bluff JS chart library by James Coglan.

1. http://arstechnica.com/apple/2012/03/anatomy-of-an-iphone-leak/
2. http://fxaguessy.fr/rapport-pfe-interception-ssl-analyse-donnees-localisation-smartphones/

[ars]: http://arstechnica.com/apple/2012/03/anatomy-of-an-iphone-leak/
[paper]: http://fxaguessy.fr/rapport-pfe-interception-ssl-analyse-donnees-localisation-smartphones/
