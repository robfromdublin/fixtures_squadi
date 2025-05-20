from playwright.sync_api import sync_playwright
import datetime as dt
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


def get_fixtures(url):
    """
    Gets all fixtures from the given url

    :param url:
    :return: list of dicts
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=10000)

        page.wait_for_selector("div.styles_tableContainer__pii69")  # Adjust to actual fixture container

        # grab fixtures table
        table = page.locator("div.styles_tableContainer__pii69")

        # fixtures = page.locator("div.styles_CompRound_VH6GP").all_inner_texts()
        fixtures = table.locator("div.styles_compRound__VH6GP")
        fix_out = []
        for i in range(fixtures.count()):
            fix = {}
            fix['Round'] = fixtures.nth(i).locator("div.styles_header__CMgUx").inner_text()
            raw_dt = fixtures.nth(i).locator("div.styles_matchStartDatetime__i4RmM").inner_text().replace('\n',' ')
            fix['StartDateTime'] = dt.datetime.strptime(raw_dt.replace(' (AEST)', ''), '%a, %b %d, %Y %I:%M %p')
            fix['Home'] = fixtures.nth(i).locator("div.styles_teamName__v4OQh").nth(0).inner_text()
            fix['Away'] = fixtures.nth(i).locator("div.styles_teamName__v4OQh").nth(1).inner_text()
            fix['Location'] = fixtures.nth(i).locator("div.ant-col").nth(7).inner_text()
            fix['Result'] = fixtures.nth(i).locator("div.styles_scoreBox__3xSTT").inner_text().replace('-','vs')
            fix_out.append(fix)

        browser.close()
    return fix_out

def get_calendar_service():
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json',
        ['https://www.googleapis.com/auth/calendar.events'])
    creds = flow.run_local_server(port=0)
    return build('calendar', 'v3', credentials=creds)

def delete_events_from_calendar(service, calendarId):
    events_result = service.events().list(calendarId=calendarId).execute()
    for event in events_result.get('items', []):
        service.events().delete(calendarId=calendarId, eventId=event['id']).execute()
    print('All events deleted')

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
    fix_out = get_fixtures("https://registration.squadi.com/competitions?yearId=7&matchid=622227&organisationKey=bede218b-68e3-45cb-9ec0-892683988b5b&competitionUniqueKey=6a795117-75e8-448c-8f21-977c2412946a&divisionId=5876&teamId=59512")
    [print(a) for a in fix_out]
    cal_id = 'f5e3d140f8e37220cefc618d30a57c8a1c9654f716175945c3eda5d0c71cb0c8@group.calendar.google.com'
    service = get_calendar_service()
    delete_events_from_calendar(service, cal_id)
    for a in fix_out:
        create_event(service,
                     calendarId=cal_id,
                     summary=f"{a['Home']} {a['Result']} {a['Away']}",
                     location=a['Location'],
                     start_dt=a['StartDateTime'],
                     end_dt=a['StartDateTime'] + dt.timedelta(hours=2))


