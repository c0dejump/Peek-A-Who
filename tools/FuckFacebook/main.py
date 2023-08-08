import argparse
import requests
from bs4 import BeautifulSoup
from terminaltables import SingleTable
import sys
from colorama import Fore, Style


def pass_the_captcha():

    url_index = "http://4wbwa6vcpvcr3vvf4qkhppgy56urmjcj2vagu2iqgp3z656xcmfdbiqd.onion.pet/"

    req = requests.get(url_index, verify=False)
    soup = BeautifulSoup(req.text, "html.parser")
    get_captcha = soup.find('pre').text
    get_id = soup.find('input', {'name': 'id'}).get('value')
    print(get_captcha)

    captcha = input("Enter the captcha: ")
    url_captcha = "{}captcha".format(url_index)

    datas = {
    "captcha": captcha,
    "id": get_id
    }
    
    req_captcha = requests.post(url_captcha, verify=False, data=datas)
    with open("token_config.py", "w") as replace_token:
        replace_token.write("""URL_TOKEN = "{}" """.format(req_captcha.url.split("=")[-1]))
    main(req_captcha.url.split("=")[-1])



def main(URL_TOKEN, params, filters):
    # Filter out empty parameters
    filtered_params = {key: value for key, value in params.items() if value}

    # Build the search URL with the filtered parameters
    search_url = "http://4wbwa6vcpvcr3vvf4qkhppgy56urmjcj2vagu2iqgp3z656xcmfdbiqd.onion.pet/search?" + "&".join(f"{key}={value}" for key, value in filtered_params.items())

    # Add the fixed parameters to the search URL
    search_url += "&s={}&r=*any*&g=*any*".format(URL_TOKEN)

    # Perform the search request
    response = requests.get(search_url, verify=False, allow_redirects=True)

    # Process the response with BeautifulSoup
    soup = BeautifulSoup(response.content, 'html.parser')

    potential_matching = ""

    if "fill" in response.text:
        pass_the_captcha()
    else:

        table = soup.find('table')

        if table:
            # Extract the data from the table
            headers = [th.text.strip() for th in table.find_all('th')]
            data = []
            i = 0

            for row in table.find_all('tr')[1:]:
                row_data = [td.text.strip() for td in row.find_all('td')]
                for rf in row_data:
                    for f in filters:
                        if f != None and f in rf:
                            row_data[i] = "\033[32m{}\033[0m".format(row_data[i])
                            potential_matching = row_data[0]
                    i += 1
                i = 0
                data.append(row_data)

            # Create a SingleTable object with the headers and data
            table_instance = SingleTable([headers] + data)

            # Make the table responsive based on the terminal size
            table_instance.inner_heading_row_border = False
            table_instance.inner_row_border = True
            table_instance.justify_columns = {index: 'center' for index in range(len(headers))}

            # Display the table
            print(table_instance.table)
            if potential_matching != "":
                print(" \033[32m\u251c \033[0m Potential matching: \033[34mhttps://www.facebook.com/profile.php?id={}\033[0m".format(potential_matching))
        else:
            print("No Results.")

if __name__ == '__main__':

    # Import the display_banner function from the banner.py file
    from static.banner import display_banner
    from token_config import URL_TOKEN

    # Display the banner with colors
    print(Fore.RED + display_banner() + Style.RESET_ALL)

    # Parser for command line arguments
    parser = argparse.ArgumentParser(description='Tool For Search information From dump facebook')
    parser.add_argument('-i', '--id', help='ID')
    parser.add_argument('-f', '--firstname', help='firstname')
    parser.add_argument('-l', '--lastname', help='lastname')
    parser.add_argument('-t', '--phone', help='phone')
    parser.add_argument('-w', '--work', help='work')
    parser.add_argument('-o', '--location', help='location')
    args = parser.parse_args()

    # Check if no arguments were provided
    if not any(vars(args).values()):
        parser.print_help()
        sys.exit(1)

    # Build the search parameters for the URL
    params = {
        'i': args.id if args.id else '',
        'f': args.firstname if args.firstname else '',
        'l': args.lastname if args.lastname else '',
        't': args.phone if args.phone else '',
        'w': args.work if args.work else '',
        'o': args.location if args.location else ''
    }
    main(URL_TOKEN, params)
