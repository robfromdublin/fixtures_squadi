from google.oauth2 import service_account
from playwright.sync_api import sync_playwright
import datetime as dt
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import os
import json

import requests
from datetime import datetime

def get_afl_fixtures(team_id: str):
    """Fetch AFL team fixtures from PlayHQ GraphQL API.

    Args:
        team_id (str): PlayHQ team ID (e.g. 'a49d026a')

    Returns:
        list[dict]: Normalised fixture list
    """

    # CRITICAL: Point directly to the AFL tenant subdomain
    url = "https://api.playhq.com/graphql"

    query = """
    query teamFixture($teamID: ID!) {
      discoverTeamFixture(teamID: $teamID) {
        fixture {
          games {
            id
            date
            status {
              value
              name
            }
            home {
              ... on DiscoverTeam {
                name
              }
              ... on ProvisionalTeam {
                name
              }
            }
            away {
              ... on DiscoverTeam {
                name
              }
              ... on ProvisionalTeam {
                name
              }
            }
            allocation {
              time
              court {
                name
                venue {
                  name
                }
              }
            }
          }
        }
      }
    }
    """

    payload = {"variables": {"teamID": team_id}, "query": query}

    # CRITICAL: Added 'tenant' and expanded 'referer' & 'user-agent'
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "tenant": "afl",  # <-- This tells the main API to use the AFL database map
        "origin": "https://www.playhq.com",
        "referer": "https://www.playhq.com/",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Extract the list of rounds
    rounds_list = data.get("data", {}).get("discoverTeamFixture", [])

    fixtures = []

    # Iterate through each round in the season
    for round_data in rounds_list:
        if not isinstance(round_data, dict):
            continue

        # Get the fixture dictionary for this specific round
        fixture_dict = round_data.get("fixture")
        if not fixture_dict or not isinstance(fixture_dict, dict):
            continue

        # Get the list of games in this round
        games = fixture_dict.get("games", [])

        # Parse the games for this round
        for g in games:
            try:
                # Safely grab team names
                home = g.get("home", {}).get("name") if g.get("home") else None
                away = g.get("away", {}).get("name") if g.get("away") else None

                # Skip empty entries or BYEs
                if not home or not away:
                    continue

                date_str = g.get("date")
                time_str = g.get("allocation", {}).get("time") if g.get("allocation") else None

                start_datetime = None
                if date_str and time_str:
                    start_datetime = datetime.fromisoformat(f"{date_str}T{time_str}")

                venue = (
                    g.get("allocation", {})
                    .get("court", {})
                    .get("venue", {})
                    .get("name")
                    if g.get("allocation")
                    else None
                )

                fixtures.append(
                    {
                        "Home": home,
                        "Away": away,
                        "Status": g.get("status", {}).get("value"),
                        "StartDateTime": start_datetime,
                        "Location": venue,
                        "Result": "vs"
                    }
                )

            except Exception:
                # Safely skip any individually broken game payloads
                continue

    return fixtures

def get_the_gap_fixtures(url, team=None, year=2025):
    """
    Extract fixtures that are only found on The Gap FC website (e.g. U6 competition)

    :param url:
    :param team: If set then table will be filtered to the team name
    :param year: Year isn't included on the page
    :return: list of dicts
    """

    with (sync_playwright() as p):
        print('Opening The Gap FC fixtures page')
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-AU",  # Set the locale to English (Australia)
            timezone_id="Australia/Brisbane"  # Set the timezone to Brisbane
        )
        page = context.new_page()
        page.goto(url, timeout=10000)
        print("Waiting for network to be idle...")
        page.wait_for_load_state('networkidle', timeout=60000)  # Wait up to 60 seconds for network to settle
        print("Network idle.")
        print('Page opened, now waiting for fixtures container')
        page.wait_for_selector("table.draw")  # Adjust to actual fixture container

        # if team is provided, filter the table to it
        if team:
            page.locator('select#filter').select_option(team)
            page.wait_for_load_state('networkidle', timeout=60000)

        fixtures = page.locator("table.draw tbody tr")
        fix_out = []
        for i in range(fixtures.count()):
            fix = {}
            row = fixtures.nth(i)
            cols = row.locator('td')
            fix['Round'] = row.locator('th.round').inner_text()
            date = cols.nth(0).inner_text()
            time = cols.nth(4).inner_text()
            fix['StartDateTime'] = dt.datetime.strptime(f'{date} {year} {time}', '%d %b %Y %I:%M%p')
            fix['Home'] = cols.nth(2).inner_text()
            fix['Away'] = cols.nth(3).inner_text()
            fix['Location'] = cols.nth(5).inner_text()
            fix['Result'] = 'vs'  # result isn't captured on these pages
            fix_out.append(fix)

        browser.close()
        print('Page closed')
    return fix_out

def get_fixtures(url):
    """
    Gets all fixtures from the given url

    :param url:
    :return: list of dicts
    """
    with sync_playwright() as p:
        print('Opening squadi page')
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-AU",  # Set the locale to English (Australia)
            timezone_id="Australia/Brisbane"  # Set the timezone to Brisbane
        )
        page = context.new_page()
        page.goto(url, timeout=10000)
        print("Waiting for network to be idle...")
        page.wait_for_load_state('networkidle', timeout=60000)  # Wait up to 60 seconds for network to settle
        print("Network idle.")
        print('Page opened, now waiting for fixtures container')
        page.wait_for_selector("div.styles_tableContainer__pii69")  # Adjust to actual fixture container

        # grab fixtures table
        table = page.locator("div.styles_tableContainer__pii69")

        # fixtures = page.locator("div.styles_CompRound_VH6GP").all_inner_texts()
        fixtures = table.locator("div.styles_compRound__VH6GP")
        fix_out = []
        print(f'Fixtures found, parsing {fixtures.count()} fixtures row by row')
        for i in range(fixtures.count()):
            fix = {}
            fix['Round'] = fixtures.nth(i).locator("div.styles_header__CMgUx").inner_text()
            fix['Home'] = fixtures.nth(i).locator("div.styles_teamName__v4OQh").nth(0).inner_text()
            fix['Away'] = fixtures.nth(i).locator("div.styles_teamName__v4OQh").nth(1).inner_text()
            if fix['Home'] != 'Bye' and fix['Away'] != 'Bye':
                raw_dt = fixtures.nth(i).locator("div.styles_matchStartDatetime__i4RmM").inner_text().replace('\n',' ')
                fix['StartDateTime'] = dt.datetime.strptime(raw_dt.replace(' (AEST)', ''), '%a, %b %d, %Y %I:%M %p')
                fix['Location'] = fixtures.nth(i).locator("div.ant-col").nth(7).inner_text()
                fix['Result'] = fixtures.nth(i).locator("div.styles_scoreBox__3xSTT").inner_text().replace('-','vs')
                fix_out.append(fix)

        browser.close()
        print('Fixtures successfully parsed')

    return fix_out

SCOPES = ['https://www.googleapis.com/auth/calendar.events']
def get_calendar_service():
    creds = None

    credentials_sa = os.environ.get("GOOGLE_SA")
    if credentials_sa:
        info = json.loads(credentials_sa)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        # If the service account environment variable isn't set then try browser authentication

        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", SCOPES
                )
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open("token.json", "w") as token:
                token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)

def delete_events_from_calendar(service, calendarId):
    page_token = None
    while True:
        events_result = service.events().list(calendarId=calendarId,
                                              maxResults=1000,
                                              singleEvents=True,
                                              pageToken=page_token).execute()
        i = 0
        for event in events_result.get('items', []):
            service.events().delete(calendarId=calendarId, eventId=event['id']).execute()
            i = i + 1
        print(f'{i} events deleted')
        page_token = events_result.get('nextPageToken')
        if not page_token:
            break

def create_event(service, calendarId, summary, location, start_dt, end_dt, description=None):
    event = {
        'summary': summary,
        'location': location,
        'description': description,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Australia/Brisbane',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Australia/Brisbane',
        },
    }

    created_event = service.events().insert(calendarId=calendarId, body=event).execute()
    print(f"Created: {created_event.get('htmlLink')}")

# Example usage with your scraped fields
if __name__ == '__main__':
    fix_out = get_afl_fixtures("a49d026a")
    print(fix_out)

    print('KPR masters fixtures')
    fix_O35 = get_fixtures("https://registration.squadi.com/livescoreSeasonFixture?organisationKey=771945e6-27e1-43bf-b81e-30f80d1a4568&yearId=8&competitionUniqueKey=8e0e372e-1695-47e7-a34b-a50cf09f1a36&divisionId=All&teamId=103776")
    fix_O45 = get_fixtures("https://registration.squadi.com/livescoreSeasonFixture?organisationKey=771945e6-27e1-43bf-b81e-30f80d1a4568&yearId=8&competitionUniqueKey=8e0e372e-1695-47e7-a34b-a50cf09f1a36&divisionId=All&teamId=103777")
    cal_id = 'f5e3d140f8e37220cefc618d30a57c8a1c9654f716175945c3eda5d0c71cb0c8@group.calendar.google.com'
    if (len(fix_O35) > 0) and (len(fix_O45) > 0):
        service = get_calendar_service()
        delete_events_from_calendar(service, cal_id)
        for a in fix_O35:
            create_event(service,
                         calendarId=cal_id,
                         summary=f"O35: {a['Home']} {a['Result']} {a['Away']}",
                         location=a['Location'],
                         start_dt=a['StartDateTime'],
                         end_dt=a['StartDateTime'] + dt.timedelta(hours=2))
        for a in fix_O45:
            create_event(service,
                         calendarId=cal_id,
                         summary=f"O45: {a['Home']} {a['Result']} {a['Away']}",
                         location=a['Location'],
                         start_dt=a['StartDateTime'],
                         end_dt=a['StartDateTime'] + dt.timedelta(hours=2))
    else:
        raise ValueError('No fixtures found so no changes made to calendar')

    # Holmes family fixtures
    print('Holmes family fixtures - need 2 add Aidan and Cillian')
    urls = {'Twins': "https://www.gapfootball.org.au/football/miniroos/fixtures/under-6-draw/",
            'Rob': "https://registration.squadi.com/livescoreSeasonFixture?organisationKey=771945e6-27e1-43bf-b81e-30f80d1a4568&yearId=8&competitionUniqueKey=8e0e372e-1695-47e7-a34b-a50cf09f1a36&divisionId=All&teamId=103777",
            'Saoirse': "https://registration.squadi.com/livescoreSeasonFixture?organisationKey=74f39f3a-6e73-48a8-b837-705aba4c4512&yearId=8&competitionUniqueKey=3b8e1b7a-2625-402e-bd40-8da1d816291c&divisionId=All&teamId=92561",
            'Cillian': "https://registration.squadi.com/competitions?yearId=7&fbclid=IwAR376c74X44fcXFJfoZC2hM5kCg5sdUgERQktM5jNOOPr3VKSGvH_4E6cc8&organisationKey=eb9849ba-05f7-4dae-8c3c-52a23f774dad&matchid=622227&competitionUniqueKey=b63aa285-57d7-4ac7-b10c-7c443fc0d80c&divisionId=5666&teamId=67848"
            }
    urls = {'Rob': "https://registration.squadi.com/livescoreSeasonFixture?organisationKey=771945e6-27e1-43bf-b81e-30f80d1a4568&yearId=8&competitionUniqueKey=8e0e372e-1695-47e7-a34b-a50cf09f1a36&divisionId=All&teamId=103777",
            'Saoirse': "https://registration.squadi.com/livescoreSeasonFixture?organisationKey=74f39f3a-6e73-48a8-b837-705aba4c4512&yearId=8&competitionUniqueKey=3b8e1b7a-2625-402e-bd40-8da1d816291c&divisionId=All&teamId=92561",
            'Cillian': "a49d026a"
           }  
    cal_id = '986b042e3651ea9db48e021d35660582e4013f3a5b6d0000c8409c56ff5a8908@group.calendar.google.com'
    service = get_calendar_service()
    delete_events_from_calendar(service, cal_id)
    for u in urls.keys():
        print(f"{u}: Extracting fixtures")
        if u == "Twins":
            fix_out = get_the_gap_fixtures(url=urls[u], team='SC Freiburg')
        elif u == "Cillian":
            fix_out = get_afl_fixtures(urls[u])
        else:
            fix_out = get_fixtures(urls[u])
        if u == "Rob":
            duration = 2  #hours
        else:
            duration = 1
        if len(fix_out) > 0:
            for a in fix_out:
                create_event(service,
                             calendarId=cal_id,
                             summary=f"{u}: {a['Home']} {a['Result']} {a['Away']}",
                             location=a['Location'],
                             start_dt=a['StartDateTime'],
                             end_dt=a['StartDateTime'] + dt.timedelta(hours=duration))
            print(f'{u}: Events successfully created')
        else:
            print(f'{u}: No fixtures found so no changes made to calendar')



