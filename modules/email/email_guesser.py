# Based on emailGuesser https://github.com/WhiteHatInspector/emailGuesser
import re, sys
import requests
from bs4 import BeautifulSoup
import time
import random
import csv
from validate_email_address import validate_email
try:
    from Queue import Queue
except:
    import queue as Queue
import threading
from threading import Thread

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

try:
    enclosure_queue = Queue()
except:
    enclosure_queue = Queue.Queue()

# Colours to be added in text output to make it more readable and user-friendly
red = "\033[31m"
green = "\033[32m"
blue = "\033[34m"
yellow = "\033[33m"
reset = "\033[39m"

# User input about all domains to be searched
domain = ["gmail.com", "yahoo.com", "hotmail.com", "orange.fr", "free.fr"]

# Lists with which we will work during the script
emails = []
emails_for_verification = []
final_emails = []
final_emails_text = []

def check_haveibeenpwnd(mailcheck, requestPwnedStartTimer):
    # Count time elapsed since last haveIbeenPwned iteration/check
    requestPwnedEndTimer = time.perf_counter()
    requestPwnedTimePassed = requestPwnedEndTimer - requestPwnedStartTimer

    # Add a random delay between 7 and 11 seconds to not let your IP get banned
    randomTimePassed = random.randint(7, 11)
    if requestPwnedTimePassed < randomTimePassed:
        time.sleep(randomTimePassed - requestPwnedTimePassed)

    url = "https://haveibeenpwned.com/account/" + mailcheck
    page = requests.get(url, verify=False)
    soup = BeautifulSoup(page.content, 'html.parser')
    results = soup.find_all(id="pwnCount")  # class_='pwnTitle'
    # print(results)
    for n in results:
        if n.text.strip() != "Not pwned in any data breaches and found no pastes (subscribe to search sensitive breaches)":
            print(red + mailcheck + reset + " was found to be " + red + "Pwned!" + reset)
            final_emails_text.append(mailcheck)
            final_emails.append(red + mailcheck + reset + "\n") # Add it to the bottom of the list as breached with no additional details

    # Restart timer
    requestPwnedStartTimer = time.perf_counter()


def email_validation(i, q, requestPwnedStartTimer):
    email = q.get()
    for n in range(len_mails):
        is_valid = validate_email(email, check_mx=True, verify=True)
        if is_valid:
            print("\033[32m{}\033[0m exist".format(email))
            url = "https://www.skypli.com/search/" + email
            page = requests.get(url, verify=False)
            # If an e-mail was found registered to only one user in Skype, print his details
            # Else if found registered to multiple users, show link to the tool user to decide if he wants to see more info
            # Else if found on breached database, return that the e-mail address is found to be Pwned
            # Else, return that the e-mail was not found to be pwned (does not exist)
            if page.status_code != 500: 
                soup = BeautifulSoup(page.content, "html.parser")
                results = soup.find_all(class_="search-results__title")
                for n in results:
                    if n.text.strip() == "1 results for " + email:
                        final_emails_text.insert(0, email)
                        print(blue + email + reset + " was found in Skype")
                        result = soup.find(class_="search-results__block-info-username")
                        url_new = "https://www.skypli.com/profile/" + result.text.strip()
                        page_new = requests.get(url_new, verify=False)
                        soup_new = BeautifulSoup(page_new.content, "html.parser")
                        email = blue + email + reset
                        result_new = soup_new.find_all(class_="profile-box__table-value")
                        for r in result_new:
                            email = email + "\n" + r.text.strip()
                        final_emails.insert(0, email + "\nMore info: " + url_new + "\n") # Add it to the top of the list in order to be shown first as Skype account
                    elif n.text.strip() != "0 results for " + email:
                        final_emails_text.insert(0, email)
                        print(blue + email + reset + " was found in multiple Skype accounts")
                        final_emails.insert(0, blue + email + reset + " Multiple skype accounts found: " + url + "\n") # Add it to the top of the list in order to be shown first as Skype account
                    else:
                        check_haveibeenpwnd(email, requestPwnedStartTimer)
            else:
                # If skypli.com is down (error 500), use tools.epieos.com/skype.php
                url = "https://tools.epieos.com/skype.php"
                my_data = {"data": email}
                page = requests.post(url, data=my_data, verify=False)
                soup = BeautifulSoup(page.content, "html.parser")
                results = soup.find_all(class_="col-md-4 offset-md-4 mt-5 pt-3 border")
                avatars = soup.find_all(src=re.compile("avatar.skype.com"))

                for n in results:
                    if len(results) == 1 and "No skype account" not in n.text.strip():
                        final_emails_text.insert(0, email)
                        print(blue + email + reset + " was found in Skype")
                        find_name = n.text.strip().find("Name : ")
                        find_skype_id = n.text.strip().find("Skype Id : ")
                        end_text = n.text.strip().rfind("</p>")
                        avatar = soup.find(src=re.compile("avatar.skype.com"))
                        email = blue + email + reset + "\n" + n.text.strip()[find_name:find_skype_id] + "\n" + n.text.strip()[find_skype_id:end_text] + "\nAvatar : " + blue + str(avatar["src"]) + reset
                        final_emails.insert(0, email + "\n") # Add it to the top of the list in order to be shown first as Skype account
                    elif len(results) > 1:
                        final_emails_text.insert(0, email)
                        print(blue + email + reset + " was found in multiple Skype accounts")
                        email = blue + email + reset + " --> Multiple skype accounts found: \n"
                        for n in results:
                            find_name = n.text.strip().find("Name : ")
                            find_skype_id = n.text.strip().find("Skype Id : ")
                            end_text = n.text.strip().rfind("</p>")
                            email += n.text.strip()[find_name:find_skype_id] + "\n" + n.text.strip()[find_skype_id:end_text] + "\n\n"
                        final_emails.insert(0, email + "\n")  # Add it to the top of the list in order to be shown first as Skype account
                        break
                    else:
                        check_haveibeenpwnd(email, requestPwnedStartTimer)   


# User inputs
def emails_guess(firstname, lastname, pseudo, birth_year, keyword):

    name_input = firstname
    last_name_input = lastname
    birth_input = birth_year
    username_input = pseudo
    keyword = keyword
    skype_input = "y"

    global len_mails
    len_mails = 0

    # for every domain specified by user, make combinations and add them to the list
    for dom in domain:
        structure = ["f!!last!!", "f!!.last!!", "f!!_last!!", "last!!f!!", "last!!.f!!", "last!!_f!!", "l!!first!!", "l!!.first!!", "l!!_first!!", "first!!l!!", "first!!.l!!", "first!!_l!!", "last!!first!!", "last!!.first!!", "last!!_first!!", "first!!last!!", "first!!.last!!", "first!!_last!!", "first!!last!!1", "first!!last!!.1", "f!!last!!1", "f!!last!!.1", "first!!.last!!1", "first!!.last!!.1"]

        # Add formats using birth year if specified by the user
        if birth_input:
            structure.append("last!!first!!" + birth_input)
            structure.append("first!!last!!" + birth_input)
            structure.append("f!!last!!" + birth_input)
            structure.append("f!!.last!!" + birth_input)
            structure.append("f!!_last!!" + birth_input)
            structure.append("first!!.l!!" + birth_input)
            structure.append("first!!_l!!" + birth_input)
            structure.append("last!!.first!!" + birth_input)
            structure.append("first!!.last!!" + birth_input)
            structure.append("last!!_first!!" + birth_input)
            structure.append("first!!_last!!" + birth_input)
            structure.append("last!!first!!" + birth_input[2:])
            structure.append("first!!last!!" + birth_input[2:])
            structure.append("f!!last!!" + birth_input[2:])
            structure.append("f!!.last!!" + birth_input[2:])
            structure.append("f!!_last!!" + birth_input[2:])
            structure.append("first!!.l!!" + birth_input[2:])
            structure.append("first!!_l!!" + birth_input[2:])
            structure.append("last!!.first!!" + birth_input[2:])
            structure.append("first!!.last!!" + birth_input[2:])
            structure.append("last!!_first!!" + birth_input[2:])
            structure.append("first!!_last!!" + birth_input[2:])
            structure.append("last!!first!!." + birth_input)
            structure.append("first!!last!!." + birth_input)
            structure.append("f!!last!!." + birth_input)
            structure.append("f!!.last!!." + birth_input)
            structure.append("f!!_last!!." + birth_input)
            structure.append("first!!.l!!." + birth_input)
            structure.append("first!!_l!!." + birth_input)
            structure.append("last!!.first!!." + birth_input)
            structure.append("first!!.last!!." + birth_input)
            structure.append("last!!_first!!." + birth_input)
            structure.append("first!!_last!!." + birth_input)
            structure.append("last!!first!!_" + birth_input)
            structure.append("first!!last!!_" + birth_input)
            structure.append("f!!last!!_" + birth_input)
            structure.append("f!!.last!!_" + birth_input)
            structure.append("f!!_last!!_" + birth_input)
            structure.append("first!!.l!!_" + birth_input)
            structure.append("first!!_l!!_" + birth_input)
            structure.append("last!!.first!!_" + birth_input)
            structure.append("first!!.last!!_" + birth_input)
            structure.append("last!!_first!!_" + birth_input)
            structure.append("first!!_last!!_" + birth_input)
            structure.append("last!!first!!." + birth_input[2:])
            structure.append("first!!last!!." + birth_input[2:])
            structure.append("f!!last!!." + birth_input[2:])
            structure.append("f!!.last!!." + birth_input[2:])
            structure.append("f!!_last!!." + birth_input[2:])
            structure.append("first!!.l!!." + birth_input[2:])
            structure.append("first!!_l!!." + birth_input[2:])
            structure.append("last!!.first!!." + birth_input[2:])
            structure.append("first!!.last!!." + birth_input[2:])
            structure.append("last!!_first!!." + birth_input[2:])
            structure.append("first!!_last!!." + birth_input[2:])
            structure.append("last!!first!!_" + birth_input[2:])
            structure.append("first!!last!!_" + birth_input[2:])
            structure.append("f!!last!!_" + birth_input[2:])
            structure.append("f!!.last!!_" + birth_input[2:])
            structure.append("f!!_last!!_" + birth_input[2:])
            structure.append("first!!.l!!_" + birth_input[2:])
            structure.append("first!!_l!!_" + birth_input[2:])
            structure.append("last!!.first!!_" + birth_input[2:])
            structure.append("first!!.last!!_" + birth_input[2:])
            structure.append("last!!_first!!_" + birth_input[2:])
            structure.append("first!!_last!!_" + birth_input[2:])

        # Add username format if specified by the user
        if username_input or keyword:
            if username_input:
                structure.append(username_input)
                structure.append("last!!first!!" + username_input)
                structure.append("first!!last!!" + username_input)
                structure.append("f!!last!!" + username_input)
                structure.append("f!!.last!!" + username_input)
                structure.append("f!!_last!!" + username_input)
                structure.append("first!!.l!!" + username_input)
                structure.append("first!!_l!!" + username_input)
            else:
                structure.append(keyword)
                structure.append("last!!first!!" + keyword)
                structure.append("first!!last!!" + keyword)
                structure.append("f!!last!!" + keyword)
                structure.append("f!!.last!!" + keyword)
                structure.append("f!!_last!!" + keyword)
                structure.append("first!!.l!!" + keyword)
                structure.append("first!!_l!!" + keyword)

            # add birth date to usernames only if specified by user
            if birth_input:
                structure.append(username_input + birth_input)
                structure.append(username_input + birth_input[2:])
                structure.append(username_input + "." + birth_input)
                structure.append(username_input + "_" + birth_input)
                structure.append(username_input + "." + birth_input[2:])
                structure.append(username_input + "_" + birth_input[2:])

        # Switch f!! with first letter of name, l!! with first letter of surname, first!! with first name and last!! with surname
        found_first = False
        found_last = False
        for x in structure:
            if x.find("first!!") != -1:
                x = x.replace("first!!", name_input)
                found_first = True
            if x.find("last!!") != -1:
                x = x.replace("last!!", last_name_input)
                found_last = True
            if x.find("f!!") != -1:
                x = x.replace("f!!", name_input[0])
            if x.find("l!!") != -1:
                x = x.replace("l!!", last_name_input[0])
            emails.append(x + "@" + dom)


    # Simple Regex for syntax checking
    regex = '^[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,})$'

    # Email addresses verification (Bulk syntax checking)
    for n in emails:

        # Syntax check
        match = re.match(regex, n)
        if match != None:
            if "gmail" in n and "_" in n or "." in n.split("@")[0]:
                pass
            else:
                # if good syntax, add to e-mail addresses to be checked
                emails_for_verification.append(n)

    # check Skypli for speed then check haveibeenpwned if not found on skype
    if len(emails_for_verification) != 0:
        # Initialize request timer for first iteration of beenPwned
        requestPwnedStartTimer = 0

        for n in emails_for_verification:
            len_mails += 1

        print(len_mails)
        print(emails_for_verification)

        try:
            for efv in emails_for_verification:
                enclosure_queue.put(efv)
            for i in range(10):
                worker = Thread(target=email_validation, args=(i, enclosure_queue, requestPwnedStartTimer))
                worker.setDaemon(True)
                worker.start()
            enclosure_queue.join()
        except KeyboardInterrupt:
            if not file_url:
                print(" {}Canceled by keyboard interrupt (Ctrl-C) ".format(INFO))
                sys.exit()
            else:
                print(" {}Canceled by keyboard interrupt (Ctrl-C), next site ".format(INFO))


    if len(final_emails) != 0:
        # Show user all e-mails that were found on skype or pwned
        print("")
        print("-------------------------------------")
        print("")
        print("Emails found:\n")
        for finalEmail in final_emails:
            print(finalEmail)
    else:
        print(red + "No e-mails found! :(" + reset)


        # Search Skype based on name and surname input to find hidden e-mail addresses
    if skype_input == "y" and len(final_emails == 0):
        print("")
        print("Searching Skype users...")
        url = "https://www.skypli.com/search/" + name_input + "%20" + last_name_input
        print(url)
        page = requests.get(url, verify=False)
        soup = BeautifulSoup(page.content, "html.parser")
        results = soup.find(class_="search-results__title")
        if page.status_code != 500:
            if results.text.strip() != "0 results for " + name_input + " " + last_name_input:
                print(results.text.strip() + ". Autocompleting list of e-mail usernames...")
                results = soup.find_all(class_="search-results__block-info-username")
                for n in results:
                    test_text = n.text.strip()
                    if test_text.find(".cid.") == -1:
                        if test_text.find("live:") != -1:
                            if len(test_text) != 21:
                                structure.append(test_text[5:])
                                # find account using same e-mail username as someone else in skype (only look for underscore followed by last 1 or 2 chars being digits)
                                # then add them also to the pool (original string is also added before reduced in size)
                                if test_text[-1].isdigit() == True and test_text[-2] == "_":
                                    structure.append(test_text[5:-2])
                                if test_text[-1].isdigit() == True and test_text[-2].isdigit() == True and test_text[-3] == "_":
                                    structure.append(test_text[5:-3])
                        else:
                            structure.append(test_text)
            else:
                print("No results on Skype for this name!")
        else:
            # If skypli.com is down (error 500), use tools.epieos.com/skype.php
            url = "https://tools.epieos.com/skype.php"
            my_data = {"data": name_input + " " + last_name_input}
            page = requests.post(url, data=my_data, verify=False)
            soup = BeautifulSoup(page.content, "html.parser")
            results = soup.find_all(class_="col-md-4 offset-md-4 mt-5 pt-3 border")
            check_results = soup.find(class_="col-md-4 offset-md-4 mt-5 pt-3 border")
            if len(results) >= 1 and "No skype account" not in check_results.text.strip():
                print("Found " + str(len(results)) + " Skype users with that name. Autocompleting list of e-mail usernames...")
                for n in results:
                    test_text = n.text.strip()
                    if test_text.find(".cid.") == -1:
                        if test_text.find("live:") != -1:
                            test_text = test_text[test_text.find("live:"):]
                            if len(test_text) != 21:
                                structure.append(test_text[5:])
                                # find account using same e-mail username as someone else in skype (only look for underscore followed by last 1 or 2 chars being digits)
                                # then add them also to the pool (original string is also added before reduced in size)
                                if test_text[-1].isdigit() == True and test_text[-2] == "_":
                                    structure.append(test_text[5:-2])
                                if test_text[-1].isdigit() == True and test_text[-2].isdigit() == True and \
                                        test_text[-3] == "_":
                                    structure.append(test_text[5:-3])
                        else:
                            test_text = test_text[test_text.find("Id : ")+5:]
                            structure.append(test_text)
            else:
                print("No results on Skype for this name!")


if __name__ == '__main__':
    firstname = "paul"
    lastname = "mabileau"
    pseudo = None
    birth_year = None
    keyword = None
    emails_guess(firstname, lastname, pseudo, birth_year, keyword)