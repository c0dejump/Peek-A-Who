# Argos_dev

![alt tag](https://github.com/c0dejump/Argos_dev/blob/master/static/Logo_Argos.png)

<img src="https://img.shields.io/badge/-Disclaimer-red">       

*Argos developers are not responsible for misuse or abuse of the tool, this is the responsibility of the end user.*

---

**For the moment most of the personal tools (except ghunt, toutatis, holehe...) that use "city" or "phone number" will be for french search**

## Features

- [x] Facial recognition by Microsoft tool
- [x] Email & Snapchat guessing
- [x] Phone number information
- [x] Holehe, Sherlock, Ignorant
- [x] Google dork
- [x] Checking qualifications/graduation (etudiant.aujourdhui.fr)

## TODO

- [ ] Ghunt
- [ ] Sraping Facebook, linkedin, whitepage (pageblanche FR), Instagram... [In progress]
- [ ] Do links/connection (same age/city...) (Reduce FP number) [In progress]
- [ ] OCR
- [ ] Image template matching
- [ ] Exif Image
- [ ] Multiple keywords

## TODO Scraping sites:
- [ ] https://copainsdavant.linternaute.com/
- [ ] Apple music (https://iforgot.apple.com/appleid), spotify, youtube, twitch, deezer, discord 
- [ ] annuaire, societe.com, Airbnb (like), fitbit
- [ ] telegram.me, vk.com, steam

## Tools used

- Holehe (https://github.com/megadose/holehe)
- Sherlock (https://github.com/sherlock-project/sherlock)
- Ignorant (https://github.com/megadose/ignorant)
- Ghunt (https://github.com/mxrch/GHunt)

## Usage

```
usage: argos.py [-h] [-i IDENTITY] [-n PHONE_NUMBER] [-m MAIL] [-p PSEUDO] [-c CITY] [-b BIRTH_YEAR] [-k KEYWORD] [--pic PICTURE]
````

```
> General:
	-i IDENTITY      Identity, exemple: -i john_doe
	-n PHONE_NUMBER  Phone number, exemple: -n +337000000
	-m MAIL          Mail adress, exemple: -m toto@gmail.com
	-p PSEUDO        Pseudo, exemple: -p codejump
> Assistance:
    -c CITY          City adress, exemple: -c Paris
	-b BIRTH_YEAR    birth year, exemple: -b 1999
	-k KEYWORD       Keyword, the script will be based on this, exemple: -k security
	--pic PICTURE    Picture, if you have a picture, it will allow you to compare it with the ones found during the scan: --pic image.png, --pic http://image.png
````
### Config

> You can put your credentials or other config in ```config.py``` file.

## Donation
<img src="https://upload.wikimedia.org/wikipedia/commons/4/46/Bitcoin.svg"> BTC : bc1qv7lxqczukam7vq626chvhfyxth9y582rpfwm8q

<img src="https://cdn4.iconfinder.com/data/icons/cryptocoins/227/ETH-64.png"> ETH : 0x406A1d5BE7185e045c2c19dFc493f03dB07b9006

<img src="https://cdn4.iconfinder.com/data/icons/office-25/63/coffee-cup-64.png"> KO-FI : https://ko-fi.com/c0dejump