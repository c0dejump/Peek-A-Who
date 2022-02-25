#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
import time
import traceback
from bs4 import BeautifulSoup
import base64
import json

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


def face_identification(known_image, unkown_image):
    #facial recognition using microsoft Face API https://azure.microsoft.com/en-us/services/cognitive-services/face/#demo
    s = requests.session()

    url = "https://azure.microsoft.com/en-us/services/cognitive-services/face/#overview"
    url_api = "https://azure.microsoft.com:443/en-us/cognitive-services/demo/faceverificationapi/" #http://httpbin.org/post" #
    _cookies = {"__RequestVerificationToken": "GRT1cJKMssjZRijFiIPCVZ4faAaSDEsf0BidLu4XaZ_-ldaKgSZjB3Dg-4zcvY6pafXKsZpzToyoP2pl9Rx6BnD6Bl81"}
    _headers = {"Content-Type": "multipart/form-data; boundary=---------------------------29466183011735581761994669456"}

    with open(known_image, "rb") as f:
        im_b64 = base64.b64encode(f.read())

    with open(unkown_image, "rb") as o:
        img_b64 = base64.b64encode(o.read())


    _data = """
    -----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"LeftImage.Url\"\r\n\r\n\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"\"\r\n\r\nSubmit\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"__RequestVerificationToken\"\r\n\r\nCt_hY1fWmL_-LwkTfaJCjKQbeCe-bgCDmQ02fmc4vHXXerFcr1nH347WF99YdRo5SjC_gU1cA_0EJfQuD_oE14h1Ffk1\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"LeftImage.Base64Url\"\r\n\r\ndata:image/JPEG;base64,{}\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"LeftImage.DemoFile\"\r\n\r\n\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"RightImage.Url\"\r\n\r\n\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"\"\r\n\r\nSubmit\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"RightImage.Base64Url\"\r\n\r\ndata:image/JPEG;base64,{}\r\n-----------------------------29466183011735581761994669456\r\nContent-Disposition: form-data; name=\"RightImage.DemoFile\"\r\n\r\n\r\n-----------------------------29466183011735581761994669456--\r\n
    """.format(im_b64.decode("utf-8"), img_b64.decode("utf-8"))



    response = s.post(url_api, headers=_headers, cookies=_cookies, data=_data, verify=False)

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        #print(soup)
        score_text = soup.find("span", {"class":"text-bold"})
        if score_text:
            score = ".".join(score_text.text.split(" ")[-1].split(".")[0:2])
            if float(score) > 0.7:
                print("   \033[34m\u251c\033[0m Score: {} between {} and {}, that's seem the same person !".format(score, known_image.split("/")[-1], unkown_image.split("/")[-1]))
                return True
    except:
        pass
        #print(response.text)

#face_identification("/mnt/c/Users/NathanFAILLENOT/OneDrive - Constellation/Images/louis_giesen.jpg", "reports/results/louis_giesen/louis.giesen.jpg")