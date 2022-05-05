# Peek-A-Who
<p align="center">
  <img src="https://github.com/c0dejump/Argos_dev/blob/master/static/logo_WHOAREU.png" height="375px" alt="Logo WhoAreU"/>
</p>


<img src="https://img.shields.io/badge/Disclaimer-WhoAreU developers are not responsible for misuse or abuse of the tool, this is the responsibility of the end user-red.svg">

---

- [Features](https://github.com/c0dejump/WhoAreU/#features)
- [TODO](https://github.com/c0dejump/WhoAreU/#todo)
- [Usage](https://github.com/c0dejump/WhoAreU/#usage)
- [Config](https://github.com/c0dejump/WhoAreU/#config)
- [Usage](https://github.com/c0dejump/WhoAreU/#usage)
- [Exemples](https://github.com/c0dejump/WhoAreU/#exemples)
- [Thanks](https://github.com/c0dejump/WhoAreU/#thanks)
- [Donations](https://github.com/c0dejump/WhoAreU/#donations)
- [Tools used](https://github.com/c0dejump/WhoAreU/#tools-used)


**For the moment most of the personal tools (except ghunt, toutatis, holehe...) that use "city" or "phone number" will be for french search**

## Features

- [x] Facial recognition by Microsoft tool
- [x] Email guessing & leak checking 
- [x] Phone number information
- [x] Holehe, Sherlock, Ignorant phomber
- [x] Google dork
- [x] Checking qualifications/graduation (etudiant.aujourdhui.fr)
- [x] societe.com informations
- [x] Social media checking
	- [x] Facebook
	- [x] Snapchat
	- [x] Instagram
	- [x] TikTok
	- [x] Telegram username
- [x] Multiple keywords 
- [x] Get etymology and city lastname (https://www.filae.com/nom-de-famille/)

## TODO

### In progress
- [ ] Short text report (maigret style) [In progress]
- [ ] Do links/connection (same age/city...) (Reduce FP number) [In progress]
 	- If school found => where is it ?
 	- If number found => what's country ? / 2 first or last digit
 	- If date or age => Do a link between us
 	- ...
- [ ] Report, he'll contain informations and picture found from networks (graph too ?)

### Image
- [ ] OCR => for the images found
- [ ] Image template matching => Before facial recognition
- [ ] Color hair recognition in keyword (red-hair, brown-hair...)
- [ ] Exif Image => If any exif (location, model phone etc...)
- [ ] If image not a person define what category is (animals, anime...)

### Others
- [ ] Ghunt (epieos? → captcha or not)
- [ ] Scraping social medias:
	- linkedin (Get CV and OCR action to get informations)
	- Twitter
	- Reddit
	- hxxps://onlyfinder.com/
- [ ] Get pub scope (possible ?): 
	-	hxxps://leadsbridge.com/blog/how-to-use-google-customer-match-like-a-pro-in-your-marketing-strategy/
	- hxxps://developers.google.com/google-ads/api/docs/remarketing/audience-types/customer-match 
	-	hxxps://cypressnorth.com/display-advertising-and-retargeting/email-address-targeting-google-facebook-twitter/#:text=To%20get%20started%20click%20on,addresses%20button%20and%20upload%20the%20.
- [ ] Adding a feature to do the difference from french research and other


## TODO Scraping sites:
- [ ] Apple music (https://iforgot.apple.com/appleid), spotify, youtube, twitch, deezer
- [ ] annuaire, Airbnb (like), fitbit
- [ ] vk.com?, steam?, discord?, pinterest


## Usage

```
usage: whoareu.py [-h] [-i IDENTITY] [-n PHONE_NUMBER] [-m MAIL] [-p PSEUDO] [-c CITY] [-b BIRTH_YEAR] [-k KEYWORD] [--pic PICTURE]
````

```
> General:    
	-i IDENTITY      Identity, exemple: -i john_doe
	-n PHONE_NUMBER  Phone number, exemple: -n +337xxxxxxxx
	-m MAIL          Mail adress, exemple: -m toto@gmail.com
	-p PSEUDO        Pseudo, exemple: -p codejump
> Assistance:         
  -c CITY          City adress, exemple: -c Paris
	-b BIRTH_YEAR    Birth year, exemple: -b 1999; -b 1990-1999
	-k KEYWORD       One or multiple keywords to refine the search, exemple: -k security -k karate
	--pic PICTURE    Picture, if you have a picture, it will allow you to compare it with the ones found during the scan: --pic image.png, --pic http://image.png
````
### Config

> You can put your credentials or other config in ```config.py``` file.

## Exemples:
```
	python3 paw.py -i john_doe
	python3 paw.py -i john_doe -c tours
	python3 paw.py -i john_doe -k securite -p codejump
	python3 paw.py -i john_doe --pic ../img/img_face.png
```


## Tools used

- Holehe (https://github.com/megadose/holehe)
- Sherlock (https://github.com/sherlock-project/sherlock)
- Ignorant (https://github.com/megadose/ignorant)
- Ghunt (https://github.com/mxrch/GHunt)
- Phomber (https://github.com/s41r4j/phomber)

## Thanks:

- @Ph4nToM00 [co creator]
- @Noobosaurus_R3x [for the name tool]
- OSINT FR community
- Login Sécurité teams [for test subject]


## Donations
<img src="https://upload.wikimedia.org/wikipedia/commons/4/46/Bitcoin.svg"> BTC : bc1qv7lxqczukam7vq626chvhfyxth9y582rpfwm8q

<img src="https://cdn4.iconfinder.com/data/icons/cryptocoins/227/ETH-64.png"> ETH : 0x406A1d5BE7185e045c2c19dFc493f03dB07b9006

<img src="https://cdn4.iconfinder.com/data/icons/office-25/63/coffee-cup-64.png"> KO-FI : https://ko-fi.com/c0dejump
