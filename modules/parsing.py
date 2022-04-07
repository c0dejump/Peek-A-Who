#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup



def get_postal_code(city):
    # If the principal website dosn't work: https://www.dcode.fr/post-code-france
    url_geocode = "http://geofree.fr/gf/zipfinder.asp"
    datas = {"todo": "2", "runok": "1", "isdom": "0", "town": "{}".format(city), "deptnb": '', "rgroup1": ''}
    req_geo = requests.post(url_geocode, data=datas, verify=False, headers={'User-agent': "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko"})
    soup = BeautifulSoup(req_geo.text, "html.parser")
    find_geocode = soup.find("td", {"bgcolor":"#CCCCCC"})
    if find_geocode and not "exactement" in find_geocode:
        geo_code = find_geocode.text.split(":")[1].strip()
        return(geo_code[0:2])
    else:
        return "00"


def parsing_data(identity, pseudo, city, keyword, birth_year):
    endpoints = []
    if pseudo:
        endpoints.append(pseudo)
    if identity:
        firstname = identity.split("_")[0] if identity else None
        lastname = identity.split("_")[1] if identity else None

        bigram_lastname = "{}{}".format(lastname[0], lastname[-1])
        trigram_lastname = "{}".format(lastname[0:3])

        list_identity = [
            "{}.{}".format(firstname, lastname), "{}-{}".format(firstname, lastname), "{}{}".format(firstname, lastname),
            "{}.{}".format(lastname, firstname), "{}-{}".format(lastname, firstname), "{}{}".format(lastname, firstname),  
            "{}.{}".format(firstname, bigram_lastname), "{}-{}".format(firstname, bigram_lastname), "{}{}".format(firstname, bigram_lastname),
            "{}.{}".format(firstname, trigram_lastname), "{}-{}".format(firstname, trigram_lastname), "{}{}".format(firstname, trigram_lastname),
            "{}.{}".format(bigram_lastname, firstname), "{}-{}".format(bigram_lastname, firstname), "{}{}".format(bigram_lastname, firstname),
            "{}_{}".format(lastname, firstname), "{}_{}".format(firstname, lastname), "_{}{}".format(firstname, lastname), "_{}{}".format(lastname, firstname),
            "{}_{}".format(firstname, bigram_lastname), "{}_{}".format(bigram_lastname, firstname), "_{}{}".format(firstname, bigram_lastname), "_{}{}".format(bigram_lastname, firstname),
            "{}_{}".format(firstname, trigram_lastname), "{}_{}".format(trigram_lastname, firstname), "_{}{}".format(firstname, trigram_lastname), "_{}{}".format(bigram_lastname, firstname)]
        """
             {}_{}1".format(firstname, lastname), "{}_{}1".format(lastname, firstname), 
            "{}_{}.1".format(firstname, lastname), "{}_{}.1".format(lastname, firstname),
            "{}_{}2".format(firstname, lastname), "{}_{}2".format(lastname, firstname),
            "{}_{}.2".format(firstname, lastname), "{}_{}.2".format(lastname, firstname)] ==> useful?
            """
        for li in list_identity:
            endpoints.append(li)
    if city and pseudo:
        postal_code = get_postal_code(city)
        list_city = [
        "{}{}".format(pseudo, city), "{}{}".format(city, pseudo), "{}_{}".format(pseudo, city), "{}.{}".format(pseudo, city),
        "{}_de{}".format(pseudo, city), "{}_of{}".format(pseudo, city), 
        "{}-de{}".format(pseudo, city), "{}-of{}".format(pseudo, city),
        "{}{}".format(pseudo, postal_code), "{}{}".format(postal_code, pseudo), "{}_{}".format(pseudo, postal_code), 
        "{}_du{}".format(pseudo, postal_code), "{}_of{}".format(pseudo, postal_code), 
        "{}-du{}".format(pseudo, postal_code), "{}-of{}".format(pseudo, postal_code) 
        ]
        for lc in list_city:
            endpoints.append(lc)
    if city and identity:
        city_identity = []
        postal_code = get_postal_code(city)
        for e in endpoints:
            list_city_identity = [
            "{}{}".format(e, city), "{}{}".format(city, e), "{}_{}".format(e, city), "{}.{}".format(e, city),
            "{}_de{}".format(e, city), "{}_of{}".format(e, city), 
            "{}-de{}".format(e, city), "{}-of{}".format(e, city),
            "{}{}".format(e, postal_code), "{}{}".format(postal_code, e), "{}_{}".format(e, postal_code), 
            "{}_du{}".format(e, postal_code), "{}_of{}".format(e, postal_code), 
            "{}-du{}".format(e, postal_code), "{}-of{}".format(e, postal_code) ]
            for lci in list_city_identity:
                city_identity.append(lci)
        for ci in city_identity:
            endpoints.append(ci)
    if keyword and pseudo:
        list_keyword = [
        "{}{}".format(pseudo, keyword), "{}{}".format(keyword, pseudo), 
        "{}_{}".format(pseudo, keyword), "{}-{}".format(pseudo, keyword), "{}.{}".format(pseudo, keyword)]
        for lk in list_keyword:
            endpoints.append(lk)
    if keyword and identity:
        keyword_identity = []
        for e in endpoints:
            list_keyword_identity = [
            "{}{}".format(e, keyword), "{}{}".format(keyword, e), "{}_{}".format(e, keyword), "{}.{}".format(e, keyword),
            "{}_of{}".format(e, keyword), "{}-of{}".format(e, keyword)]
            for lki in list_keyword_identity:
                keyword_identity.append(lki)
        for ki in keyword_identity:
            endpoints.append(ki)
    if birth_year:
        birth_identity = []
        for e in endpoints:
            list_birth_identity = [
                "{}{}".format(e, birth_year), "{}{}".format(birth_year, e), "{}_{}".format(e, birth_year), "{}.{}".format(e, birth_year),
                "{}_de{}".format(e, birth_year), "{}_of{}".format(e, birth_year), 
                "{}-de{}".format(e, birth_year), "{}-of{}".format(e, birth_year)]
            for lbi in list_birth_identity:
                birth_identity.append(lbi)
        for bi in birth_identity:
            endpoints.append(bi)
    return endpoints