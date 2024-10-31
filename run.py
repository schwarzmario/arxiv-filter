import os
import time
import re
from datetime import datetime 
from pytz import timezone
import requests
import arxiv
import xdg.BaseDirectory

dry_run = False

class Query(object):
    def __init__(self, query):
        self.date = datetime(*query['updated_parsed'][:6], tzinfo=timezone('GMT'))
        self.url = query['arxiv_url']
        self.title = query['title']
        self.authors = ', '.join(query['authors'])
        self.abstract = query['summary']
        self.date_str = query['published']
        self.id = 'v'.join(query['id'].split('v')[:-1])
        self.categories = [tag['term'] for tag in query['tags']]

    @property
    def is_recent(self):
        curr_time = datetime.now(timezone('GMT'))
        delta_time = curr_time - self.date
        assert delta_time.total_seconds() > 0
        return delta_time.days < 8

    def __hash__(self):
        return self.id

    def __str__(self):
        s = ''
        s += self.title + '\n'
        s += self.url + '\n'
        s += self.authors + '\n'
        s += ', '.join(self.categories) + '\n'
        s += self.date.ctime() + ' GMT \n'
        s += '\n' + self.abstract + '\n'
        return s.encode('utf-8')



def share_categories(list1, list2):
    """True if at least 1 category in list1 also exists in list2"""
    return not set(list1).isdisjoint(list2)

def is_recent(last_updated_time):
    curr_time = datetime.now(timezone('GMT'))
    delta_time = curr_time - last_updated_time
    assert delta_time.total_seconds() > 0
    return delta_time.days < 8

class ArxivFilter(object):
    def __init__(self, categories, keywords, mailgun_sandbox_name, mailgun_api_key, mailgun_email_recipient):
        self._categories = categories
        self._keywords = keywords       #want to rename this to queries
        self._mailgun_sandbox_name = mailgun_sandbox_name
        self._mailgun_api_key = mailgun_api_key
        self._mailgun_email_recipient = mailgun_email_recipient

    @property
    def _previous_arxivs_fname(self):
        return os.path.join(xdg.BaseDirectory.xdg_config_home, 'arxiv-filter', 'previous_arxivs.txt')
        
    def _get_previously_sent_arxivs(self):
        if os.path.exists(self._previous_arxivs_fname):
            with open(self._previous_arxivs_fname, 'r') as f:
                return set(f.read().split('\n'))
        else:
            return set()

    def _save_previously_sent_arxivs(self, new_results):
        prev_arxivs = list(self._get_previously_sent_arxivs())
        prev_arxivs += [r.entry_id for r in new_results]
        prev_arxivs = list(set(prev_arxivs))
        with open(self._previous_arxivs_fname, 'w') as f:
            f.write('\n'.join(prev_arxivs))

    def _get_results_from_last_day(self, max_results=10):

        client = arxiv.Client()
        print(self._categories)

        resultslist = []
        # get all queries in the categories in the last day
        for query in self._keywords:
            print("Enter query " + query)
            num_query_added = 0
            outOfTime = False
            while True:
                search = arxiv.Search(query = query, max_results = max_results, sort_by = arxiv.SortCriterion.SubmittedDate)
                results = client.results(search, offset=num_query_added)
                for r in results:
                    num_query_added += 1
                    if(not share_categories(r.categories, self._categories)):
                        continue
                    if(not is_recent(r.updated)):
                        outOfTime = True
                        continue
                    resultslist.append(r)
                if outOfTime:   #hit an outdated entry
                    break

        # get rid of duplicates
        results_dict = {r.entry_id: r for r in resultslist}
        unique_keys = set(results_dict.keys())
        resultslist = [results_dict[k] for k in unique_keys]

        # sort from most recent to least
        resultslist = sorted(resultslist, key=lambda r: (datetime.now(timezone('GMT')) - r.updated).total_seconds())

        # filter if previously sent
        prev_arxivs = self._get_previously_sent_arxivs()
        resultslist = [r for r in resultslist if r.entry_id not in prev_arxivs]
        self._save_previously_sent_arxivs(resultslist)

        #for r in resultslist:
        #    if(not share_categories(r.categories, self._categories)):
        #        continue
        #    print(r.title)
        #    print(r.categories)
        #    print("recent? {}".format(is_recent(r.updated)))

        return resultslist

    def _send_email(self, txt):
        request = requests.post(
                "https://api.mailgun.net/v3/{0}/messages".format(self._mailgun_sandbox_name),
                auth=("api", self._mailgun_api_key),
                data={"from": "ArXiv Filter <mailgun@{0}>".format(self._mailgun_sandbox_name),
                      "to": [self._mailgun_email_recipient],
                      "subject": "ArxivFilter {0}".format(datetime.now(timezone('GMT')).ctime()),
                      "text": txt})

        print('Status: {0}'.format(request.status_code))
        print('Body:   {0}'.format(request.text))

    def _to_stdout(self, txt):
        print(txt)
    
    def _output(self, text):
        if dry_run:
            self._to_stdout(text)
        else:
            self._send_email(text)

    def run(self):
        results = self._get_results_from_last_day()
        results_str = "The latest arXiv Entries are here:\n\n"
        for r in results:
            results_str += '-----------------------------\n'
            results_str += r.entry_id + '\n\n'
            results_str += r.title + '\n\n'
            results_str += r.summary + '\n\n'
        self._output(results_str)

FILE_DIR = os.path.join(xdg.BaseDirectory.xdg_config_home, 'arxiv-filter')

with open(os.path.join(FILE_DIR, 'categories.txt'), 'r') as f:
    categories = [line.strip() for line in f.read().split('\n') if len(line.strip()) > 0]

with open(os.path.join(FILE_DIR, 'keywords.txt'), 'r') as f:
    keywords = [line.strip() for line in f.read().split('\n') if len(line.strip()) > 0]

with open(os.path.join(FILE_DIR, 'mailgun-sandbox-name.txt'), 'r') as f:
    mailgun_sandbox_name = f.read().strip()

with open(os.path.join(FILE_DIR, 'mailgun-api-key.txt'), 'r') as f:
    mailgun_api_key = f.read().strip()

with open(os.path.join(FILE_DIR, 'mailgun-email-recipient.txt'), 'r') as f:
    mailgun_email_recipient = f.read().strip()


af = ArxivFilter(categories=categories,
                 keywords=keywords,
                 mailgun_sandbox_name=mailgun_sandbox_name,
                 mailgun_api_key=mailgun_api_key,
                 mailgun_email_recipient=mailgun_email_recipient)
af.run()



