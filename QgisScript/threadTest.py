# -*- coding: utf-8 -*-

from osgeo import ogr
import threading, time

PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_37612068.pdf"
# PDF_FILE_NAME = u"C:\\Temp\\(B090)온맵_358124.pdf"
pdfFilePath = PDF_FILE_NAME


def threadOpenPdf(pdfFilePath):
    srcDriver = ogr.GetDriverByName("PDF")
    pdf = srcDriver.Open(pdfFilePath, 0)
    return pdf


from multiprocessing.pool import ThreadPool

pool = ThreadPool(processes=1)

print "RUN Thread"
t = pool.apply_async(threadOpenPdf, (pdfFilePath,))  # tuple of args for foo

print "GOGO Main!!!"
print "Check Alive"

# while t._job:
# while True:
while pool._state:
    print ".",
    # time.sleep(1)

return_val = t.get()  # get the return value from your function.

print "RETURN"
print return_val
