#!/usr/bin/env python

"""
A bot to find submissions in /r/FreeEbooks that are no longer free and to mark
them as expired. The bot also sends mail to the mods telling them of any new
submissions that this bot can't handle (mark as expired when the time comes) on
its own. This was made by /u/penguinland.

To install PRAW without root,
- Choose a local directory to install to, such as ~/local.
- Try running:
    easy_install --prefix=~/local praw
- It will fail, but it will tell you what you need to add to your PYTHONPATH
- In your .zshrc (or .bashrc, or whatever), set PYTHONPATH accordingly.
- Remember to export PYTHONPATH from your .zshrc as well!
- Run the command again, and it should succeed this time:
    easy_install --prefix=~/local praw
- You'll also need to install httplib2 and pylru:
    easy_install --prefix=~/local httplib2
    easy_install --prefix=~/local pylru
- If you run this bot as a cron job, remember to set the PYTHONPATH up
  correctly in your crontab as well!
"""

import httplib2
import os
import praw
import pylru
import re
import time
import urllib2

TEST_DATA = False  # Set to True to run over /r/chtorrr
DRY_RUN = True  # Set to False to make actual changes

USERNAME = "expired_link_bot"
PASSWORD = ""  # Remember to put in the password when actually using this!

ONE_HOUR_IN_SECONDS = 60 * 60
CACHE_FILE = "expired_link_bot_cache.txt"

EXPIRED_FLAIR = "Expired"  # Flair on /r/FreeEbooks
EXPIRED_CSS_CLASS = "closed"

# Note that this is a template. You need to supply the current price of the
# book and the permalink to the Reddit submission for this comment to make
# sense to readers.
EXPIRED_MESSAGE = u"""
This link points to an ebook that is no longer free (current price: %s), and
consequently has been marked as expired.

I am a bot. If I have made a mistake, please [message the
moderators](http://www.reddit.com/message/compose?to=/r/FreeEBOOKS&subject=expired_link_bot&message=%s).
"""

def GetPriceSelector(url):
  """
  Given a string containing a URL, if it matches something where we know how to
  find the price, return a string containing the regular expression that will
  have the price in its first group. If we don't know how to find the price on
  this URL, return the empty string.
  """
  if url.startswith(("http://www.amazon.com/",
                     "http://amzn.com/",
                     "http://www.amazon.co.uk/",
                     "https://www.amazon.co.uk/",
                     "http://www.amazon.ca/")):
    return r'\s+class="priceLarge"\s*>([^<]*)<'
  if url.startswith("https://www.smashwords.com/"):
    return r'class="panel-title text-center">\s*Price:([^<]*)<'
  if url.startswith("http://www.barnesandnoble.com/"):
    return r'itemprop="price" data-bntrack="Price" data-bntrack-event="click">([^<]*)<'
  # Although Google Play links work fine from my home computer, this webserver
  # only gets 403 (Forbidden) replies from Google. Presumably there have been
  # other scrapers on this server doing mean things in the past, so Google has
  # blocked all of them. If this bot gets migrated to a different server, try
  # uncommenting these lines.
  #if url.startswith("https://play.google.com/"):
  #  return r'<meta content="([^"]*)" itemprop="price">'
  # Add other matches here
  return ""

def GetPrice(url):
  """
  Given a string containing a URL of an ebook, return a string containing its
  current price. If we do not know how to get the price, or if we're unable to
  get the price, return the empty string.
  """
  price_selector = GetPriceSelector(url)
  if not price_selector:
    # The url is on a website where we don't know how to find the price
    return ""

  try:
    # We sleep here to ensure that we send websites at most 1 qps.
    time.sleep(1)

    # Get the contents of the webpage about this ebook. We use iri2uri to encode
    # any stray unicode characters that might be in the URL (which web browsers
    # can handle automatically, but which urllib2 doesn't know about).
    request = urllib2.urlopen(httplib2.iri2uri(url))
    html = request.read()
    # Remember to convert to unicode if the website uses some other encoding.
    encoding = request.info().typeheader
    encoding = encoding.split("charset=")[-1]
    html = html.decode(encoding)
    price = re.search(price_selector, html).group(1).strip()
    return price
  except:
    print "Unable to download/parse URL:"
    print url
    return ""

def IsKnownFree(url):
  """
  Given a string containing a URL, return whether we know this site only hosts
  permanently free ebooks.
  """
  return url.startswith(("http://ebooks.adelaide.edu.au/",
                         "http://www.gutenberg.org/",
                         "http://gutenberg.org/",
                         "http://www.topfreebooks.org/",
                         # Feedbooks' paid content is in feedbooks.com/item/
                         "http://www.feedbooks.com/book/",
                         "http://www.feedbooks.com/userbook/",
                         "https://librivox.org/",
                         "https://www.librivox.org/",
                         "http://podiobooks.com/",
                         "https://openlibrary.org/"))

def LoadCacheFromFile():
  """
  This function returns a pylru.lrucache object containing (key, value) pairs.
  The keys are strings containing the URLs of submissions which the bot can't
  handle on its own but which have already been sent to the mods. The values are
  just dummy values to be ignored. We try to read CACHE_FILE. If we can, we
  return a pylru.lrucache object containing its contents, with the top line of
  the file being the most recently used entry and the last line of the file
  being the least recently used entry. If we cannot read the file, we return an
  empty pylru.lrucache object.
  This function should return a cache containing the same state as the cache
  last passed to StoreCacheToFile().
  """
  cache = pylru.lrucache(100)  # Cache can store 100 submissions

  try:
    f = open(CACHE_FILE)
    contents = f.readlines()
    f.close()
  except:  # Can't read the file; give up and start from scratch.
    print "WARNING: Unable to load cache. Starting over with an empty cache."
    return cache

  # The most recently used line is first in the file, which means it should be
  # inserted into the cache last.
  for line in reversed(contents):
    cache[line.strip()] = True  # Dummy value
  return cache

def StoreCacheToFile(cache):
  """
  cache is a pylru.lrucache object. We write the keys of this cache to
  CACHE_FILE, one line per entry. These entries will be sorted from most
  recently used (first line of the file) to least recently used (last line of
  the file). Calling LoadCacheFromFile() ought to return the same cache that s
  written out here.
  """
  # We don't want to overwrite the old contents of the cache until the entire
  # new version can be written. Consequently, we will write to a temporary file
  # and then rename it to be CACHE_FILE itself.
  out_file_name = "%s.tmp" % CACHE_FILE
  out_file = open(out_file_name, "w")
  # pylru claims that iterating through the keys in the cache iterates from
  # most recently used to least recently used.
  for key in cache:
    out_file.write(key)
    out_file.write("\n")
  out_file.close()
  # Now that we're done successfully writing out the file, rename it to the
  # proper filename.
  os.rename(out_file_name, CACHE_FILE)

def CheckSubmissions(subreddit):
  """
  Given a subreddit, marks expired links and returns a list of the submissions
  that were marked. It also returns a list of submissions we were unable to
  process (either because we don't know how to find the price or because we
  were unable to get the price).
  """
  modified_submissions = []
  needs_review_submissions = []
  needs_review_cache = LoadCacheFromFile()

  for rank, submission in enumerate(subreddit.get_hot(limit=200)):
    submission.rank = rank  # Used when creating digests for the mods

    # Skip anything already marked as expired, unless it's test data.
    if submission.link_flair_css_class == EXPIRED_CSS_CLASS and not TEST_DATA:
      continue

    price = GetPrice(submission.url)
    # The price might be the empty string if we're unable to get the real price.
    if not price:
      if IsKnownFree(submission.url):  # No human review needed!
        continue

      if submission.url not in needs_review_cache:
        needs_review_submissions.append(submission)  # Send it to the mods!
      # Regardless of whether we need to tell the mods, move this submission to
      # the front of the cache.
      needs_review_cache[submission.url] = True  # Dummy value
      continue

    # This next line is a little hard for non-Python people to read. It's
    # asking whether any nonzero digit is contained in the price.
    if not any(digit in price for digit in "123456789"):
      continue  # It's still free!

    # If we get here, this submission is no longer free. Make a comment
    # explaining this and set the flair to expired.
    if not DRY_RUN:
      submission.add_comment(EXPIRED_MESSAGE % (price, submission.permalink))
      subreddit.set_flair(submission, EXPIRED_FLAIR, EXPIRED_CSS_CLASS)
    submission.list_price = price  # Store this to put in the digest later.
    modified_submissions.append(submission)
  if not DRY_RUN:  # Don't change the next run's cache if this is just a test
    StoreCacheToFile(needs_review_cache)
  return modified_submissions, needs_review_submissions

def MakeDigest(submissions, FormatSubmission, digest_template):
  """
  - submissions is a list of submissions to put in the digest.
  - FormatSubmission is a functon that takes a submision and returns a string
    containing the relevant information.
  - digest_template is a string template that will be used to create the
    digest. It must have places for the number of submissions and for a string
    representation of the submissions.
  - We return a string containing the summary of these submissions, intended to
    be sent to the moderators.
  """
  formatted_submissions = [FormatSubmission(sub) for sub in submissions]
  digest = (digest_template %
            (len(formatted_submissions), "\n\n".join(formatted_submissions)))
  return digest

def RunIteration(r):
  """
  Given a PRAW Reddit object, do everything the bot is supposed to do: grab
  stuff from the subreddit, find the expired submissions, and send an update to
  the mods. This returns nothing.
  """
  if TEST_DATA:
    subreddit = r.get_subreddit("chtorrr")
  else:
    subreddit = r.get_subreddit("freeebooks")

  modified_submissions, needs_review_submissions = CheckSubmissions(subreddit)
  # We no longer use the detailed digest of modified submissions, but I leave
  # it here in case we ever need it again.
  #modified_digest = MakeDigest(
  #    modified_submissions,
  #    (lambda sub: "#%d: [%s](%s) (%s)" %
  #                 (sub.rank, sub.title, sub.permalink, sub.list_price)),
  #    u"Marked %d submission(s) as expired:\n\n%s")
  modified_digest = ("Marked %d submission(s) as expired. See the "
      "[moderation log]"
      "(http://www.reddit.com/r/FreeEBOOKS/about/log/?mod=expired_link_bot) "
      "for details." % len(modified_submissions))
  needs_review_digest = MakeDigest(
      needs_review_submissions,
      (lambda sub: "#%d: ([direct link](%s)) [%s](%s)" %
                   (sub.rank, sub.url, sub.title, sub.permalink)),
      "Human review needed for %d new submission(s):\n\n%s")

  if DRY_RUN:
    recipient = "penguinland"  # Send test digests only to me.
  else:
    recipient = "/r/FreeEbooks"  # Send the real digest to the mods
  r.send_message(recipient, "Bot Digest",
      modified_digest + "\n\n" + needs_review_digest)

if __name__ == "__main__":
  # useragent string
  r = praw.Reddit("/r/FreeEbooks expired-link-marking bot "
                  "by /u/penguinland v. 2.1")
  r.login(USERNAME, PASSWORD)

  RunIteration(r)
