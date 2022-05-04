import sys, re
import requests
import time
import traceback
from bs4 import BeautifulSoup
from static.colors import info, match, p_match, no_match, error, separator

try:
    from fake_useragent import UserAgent
except:
    UserAgent = ["Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; LCJB; rv:11.0) like Gecko", "c0dejump"]


requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def get_city(lastname, s):
    url_city = "https://www.filae.com/nom-de-famille/nom-{}-par-departement".format(lastname)
    req_city = s.get(url_city, verify=False, timeout=10, headers={'User-agent': UserAgent().random})
    soup = BeautifulSoup(req_city.text, "html.parser") 
    for r in soup.find_all('tr'):
        city = r.find("td", {'class': 'nameCellDepRank'})
        number = r.find("td", {'class': 'numberCell'})
        if city.find("a") != None:
            print("     \u251c {}: {}".format(city.find("a").text.strip().replace("\r\n", " ").replace("  ", ""), number.text.strip().replace("\r\n", " ").replace("  ", "")))

def lastname_ety(dirname, lastname):
    print("\033[36m Etymology search\033[0m")
    print(separator)
    s = requests.session()
    url = "https://www.filae.com/nom-de-famille/{}.html".format(lastname)
    req = s.get(url, verify=False, timeout=10, headers={'User-agent': UserAgent().random})
    #print(req.text)
    if "Total" in req.text:
        soup = BeautifulSoup(req.text, "html.parser")
        patronyme = soup.find('ul', {'class': 'patronyme'})
        result = patronyme.text.strip().replace("  ", "").replace("\r", " ").split("\n")
        print("   \u251c {}: {}:".format(lastname, result[3]))
        get_city(lastname, s)
    print(separator)



if __name__ == '__main__':
    lastname = "faillenot"
    lastname_ety(lastname)