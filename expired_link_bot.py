#!/usr/bin/env python

"""
A bot to find submissions in /r/FreeEbooks that are no longer free and to mark
them as expired. This was made by /u/penguinland.

To install praw without root,
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
import praw
import pylru
import re
import time
import urllib2

TEST_DATA = False  # Set to True to run over /r/chtorrr
DRY_RUN = True  # Set to False to make actual changes

username = "expired_link_bot"
password = ""  # Remember to put in the password when actually using this!

ONE_HOUR_IN_SECONDS = 60 * 60

expired_flair = "Expired"  # Flair on /r/FreeEbooks
expired_css_class = "closed"

# Note that this is a template. You need to supply the current price of the
# book and the permalink to the Reddit submission for this comment to make
# sense to readers.
expired_message = u"""
This link points to an ebook that is no longer free (current price: %s), and
consequently has been marked as expired.

I am a bot. If I have made a mistake, please [message the
moderators](http://www.reddit.com/message/compose?to=/r/FreeEBOOKS&subject=expired_link_bot&message=%s).
"""

# This LRU cache is full of (key, value) pairs. The values are dummy variables
# to be ignored, and the keys are URLs to submissions that the bot can't handle
# on its own. We keep a cache so that we only send each "needs human review"
# submission to the mods once.
needs_review_cache = pylru.lrucache(100)  # Cache can store 100 submissions

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
                         "https://openlibrary.org/"))

def CheckSubmissions(subreddit):
  """
  Given a subreddit, marks expired links and returns a list of the submissions
  that were marked. It also returns a list of submissions we were unable to
  process (either because we don't know how to find the price or because we
  were unable to get the price).
  """
  modified_submissions = []
  needs_review_submissions = []

  for rank, submission in enumerate(subreddit.get_hot(limit=200)):
    submission.rank = rank  # Used when creating digests for the mods

    # Skip anything already marked as expired, unless it's test data.
    if submission.link_flair_css_class == expired_css_class and not TEST_DATA:
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
      submission.add_comment(expired_message % (price, submission.permalink))
      subreddit.set_flair(submission, expired_flair, expired_css_class)
    submission.list_price = price  # Store this to put in the digest later.
    modified_submissions.append(submission)
  return modified_submissions, needs_review_submissions

def MakeModifiedDigest(modified_submissions):
  """
  Given a list of modified submissions, returns a string containing a summary
  of the modified submissions, intended to be sent to the moderators.
  """
  formatted_submissions = [
      u"#%d: [%s](%s) (%s)" %
      (sub.rank, sub.title, sub.permalink, sub.list_price)
      for sub in modified_submissions]
  digest = (u"Marked %d submission(s) as expired:\n\n%s" %
            (len(formatted_submissions), u"\n\n".join(formatted_submissions)))
  return digest

def MakeNeedsReviewDigest(needs_review_submissions):
  """
  Given a list of submissions the bot couldn't process, returns a string
  containing a summary of these submissions, intended to be sent to the
  moderators.
  """
  formatted_submissions = [
      u"#%d: ([direct link](%s)) [%s](%s)" %
      (sub.rank, sub.url, sub.title, sub.permalink)
      for sub in needs_review_submissions]
  digest = (u"Human review needed for %d new submission(s):\n\n%s" %
            (len(formatted_submissions), u"\n\n".join(formatted_submissions)))
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
  #modified_digest = MakeModifiedDigest(modified_submissions)
  modified_digest = ("Marked %d submission(s) as expired. See the "
      "[moderation log]"
      "(http://www.reddit.com/r/FreeEBOOKS/about/log/?mod=expired_link_bot) "
      "for details." % len(modified_submissions))
  needs_review_digest = MakeNeedsReviewDigest(needs_review_submissions)

  if DRY_RUN:
    recipient = "penguinland"  # Send test digests only to me.
  else:
    recipient = "/r/FreeEbooks"  # Send the real digest to the mods
  r.send_message(recipient, "Bot Digest",
      modified_digest + "\n\n" + needs_review_digest)

if __name__ == "__main__":
  # useragent string
  r = praw.Reddit("/r/FreeEbooks expired-link-marking bot "
                  "by /u/penguinland v. 2.0")
  r.login(username, password)

  if DRY_RUN:
    RunIteration(r)
  else:
    while True:
      # We want to run once per day, at roughly the same time every day,
      # regardless of when this script is started. This was originally done by
      # running it as a cron job, but now that we have a cache of stuff that
      # has already been sent to the mods, we need to do this cron-like
      # behavior from within the Python script so we can keep the cache around.
      # So, check the time once every hour, and run once each morning.
      now = time.localtime()
      if now.tm_hour == 4:  # 4 AM PST, 7 AM EST, Noon GMT
        RunIteration(r)
	# Sleep until it's early in the next hour, so that we'll wake up at a
	# good time for tomorrow's run (3 minutes into the hour).
        now = time.localtime()  # Update the time now that today's run is over
        time.sleep(ONE_HOUR_IN_SECONDS - 60 * (now.tm_min - 3))
      else:  # It's the wrong hour; wait some more.
        time.sleep(ONE_HOUR_IN_SECONDS)
