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
import sys
import time
import urllib2

TEST_DATA = False  # Set to True to run over /r/chtorrr
DRY_RUN = True  # Set to False to make actual changes

USERNAME = "expired_link_bot"
PASSWORD = ""  # Remember to put in the password when actually using this!

DIGEST_RECIPIENT = "/r/FreeEbooks"  # Send the real digest to the mods

MAX_SUBMISSIONS = 200  # Number of submissions to examine; size of caches

NEEDS_REVIEW_CACHE_FILE = "needs_review_cache.txt"
ALREADY_EXPIRED_CACHE_FILE = "already_expired_cache.txt"

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

HELP_MESSAGE = """The following command line arguments are supported:
-h or --help         print this message
-x or --makechanges  actually change flair and leave comments
-t or --testdata     run over /r/Chtorrr instead of /r/FreeEbooks
-p or --password     use the next argument as the password to log in
-r or --recipient    send the digest to the name in the next argument

Example: ./expired_link_bot -t -p "BotPassword123" -r "myusername" """

def ProcessCommandLine():
  global DRY_RUN, TEST_DATA, PASSWORD, DIGEST_RECIPIENT
  argv = sys.argv[1:]
  argv.reverse()
  has_set_digest_recipient = False
  while argv:
    arg = argv.pop()
    if arg == "-h" or arg == "--help":
      print HELP_MESSAGE
      sys.exit()
    elif arg == "-x" or arg == "--makechanges":
      DRY_RUN = False
    elif arg == "-t" or arg == "--testdata":
      TEST_DATA = True
    elif arg == "-p" or arg == "--password":
      PASSWORD = argv.pop()
    elif arg == "-r" or arg == "--recipient":
      DIGEST_RECIPIENT = argv.pop()
      has_set_digest_recipient = True
    else:
      print "WARNING: unexpected command line argument; ignoring."
  if (DRY_RUN or TEST_DATA) and not has_set_digest_recipient:
    DIGEST_RECIPIENT = "penguinland"  # Send test digests only to me.

def GetPriceSelector(url):
  """
  Given a string containing a URL, if it matches something where we know how to
  find the price, return a string containing the regular expression that will
  have the price in its first group. If we don't know how to find the price on
  this URL, return the empty string.
  """
  # Handle Amazon Mobile links first, and then do all other Amazon links as
  # though they're not mobile.
  if url.startswith("http://www.amazon.com/gp/aw/d/"):
    return r'<b>Price:</b>&nbsp;([^&]*)&nbsp;<br />'
  if url.startswith(("http://www.amazon.com/",
                     "http://amzn.com/",
                     "http://www.amazon.co.uk/",
                     "https://www.amazon.co.uk/",
                     "http://www.amazon.ca/")):
    return r'\s+class="priceLarge"\s*>([^<]*)<'
  if url.startswith(("http://www.smashwords.com/",
                     "https://www.smashwords.com/")):
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
  if url.startswith("http://bookshout.com"):
    return r'<span>Our Price:</span>([^<]*)</p>'
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

    # Recall that we've already passed the URL through iri2uri, so we don't
    # need to do it here.
    request = urllib2.urlopen(url)
    html = request.read()
    # Remember to convert to normal strings if the website uses some other
    # encoding.
    encoding = request.info().typeheader
    encoding = encoding.split("charset=")[-1]
    html = html.decode(encoding)
    price = re.search(price_selector, html).group(1).strip()
    return price
  except:
    print "Unable to download/parse URL:"
    print url
    print "(type, value, traceback):"
    print sys.exc_info()
    return ""

def IsKnownFree(url):
  """
  Given a string containing a URL, return whether we know this site only hosts
  permanently free ebooks.
  """
  return url.startswith(("http://ebooks.adelaide.edu.au/",
                         "http://www.gutenberg.org/",
                         "http://gutenberg.org/",
                         "https://archive.org/",
                         "http://www.topfreebooks.org/",
                         # Feedbooks' paid content is in feedbooks.com/item/
                         "http://www.feedbooks.com/book/",
                         "http://www.feedbooks.com/userbook/",
                         "https://librivox.org/",
                         "https://www.librivox.org/",
                         "http://podiobooks.com/",
                         "http://quirkystories.com/",
                         "https://openlibrary.org/"))

def LoadCacheFromFile(filename):
  """
  This function returns a pylru.lrucache object containing (key, value) pairs.
  The keys are strings containing the URLs of submissions. The values are just
  dummy values to be ignored. We try to read the file whose name is given as an
  argument. If we can, we return a pylru.lrucache object containing its
  contents, with the top line of the file being the most recently used entry
  and the last line of the file being the least recently used entry. If we
  cannot read the file, we return an empty pylru.lrucache object. This function
  should return a cache containing the same state as the cache last passed to
  StoreCacheToFile().
  """
  cache = pylru.lrucache(MAX_SUBMISSIONS)

  try:
    f = open(filename)
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

def StoreCacheToFile(cache, filename):
  """
  cache is a pylru.lrucache object. We write the keys of this cache to
  filename (which is a string), one line per entry. These entries will be
  sorted from most recently used (first line of the file) to least recently used
  (last line of the file). Calling LoadCacheFromFile() ought to return the same
  cache that is written out here.
  """
  # We don't want to overwrite the old contents of the cache until the entire
  # new version can be written, in case this program is killed in the middle of
  # writing it. Consequently, we will write to a temporary file and then rename
  # it to be filename itself.
  tmp_filename = "%s.tmp" % filename
  tmp_file = open(tmp_filename, "w")
  # pylru claims that iterating through the keys in the cache iterates from
  # most recently used to least recently used.
  for key in cache:
    tmp_file.write(key)
    tmp_file.write("\n")
  tmp_file.close()
  # Now that we're done successfully writing out the file, rename it to the
  # proper filename.
  os.rename(tmp_filename, filename)

def CheckSubmissions(subreddit):
  """
  Given a PRAW subreddit, marks expired links and returns a list of the
  submissions that were marked. It also returns a list of submissions we were
  unable to process (either because we don't know how to find the price or
  because we were unable to get the price).
  """
  modified_submissions = []
  needs_review_submissions = []
  needs_review_cache = LoadCacheFromFile(NEEDS_REVIEW_CACHE_FILE)
  already_expired_cache = LoadCacheFromFile(ALREADY_EXPIRED_CACHE_FILE)

  for rank, submission in enumerate(subreddit.get_hot(limit=MAX_SUBMISSIONS)):
    submission.rank = rank  # Used when creating digests for the mods
    # Both urllib2.urlopen() and the file writer to save the cache have trouble
    # when a submission's URL contains Unicode characters. Consequently, we
    # encode any stray Unicode characters right away so we don't need to worry
    # about it later.
    submission.url = httplib2.iri2uri(submission.url)

    # Skip anything already marked as expired, unless it's test data.
    if (submission.link_flair_css_class == EXPIRED_CSS_CLASS or
        submission.url in already_expired_cache) and not TEST_DATA:
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
      # Add it to the cache, so that if we have made a mistake and this
      # submission is later un-expired, we don't re-expire it the next day.
      already_expired_cache[submission.url] = True  # Dummy value
    submission.list_price = price  # Store this to put in the digest later.
    modified_submissions.append(submission)
  if not DRY_RUN and not TEST_DATA:
    # Don't change the next run's cache if this is just a test
    StoreCacheToFile(already_expired_cache, ALREADY_EXPIRED_CACHE_FILE)
    StoreCacheToFile(needs_review_cache, NEEDS_REVIEW_CACHE_FILE)
  return modified_submissions, needs_review_submissions

def MakeDigest(submissions, FormatSubmission, digest_template):
  """
  - submissions is a list of submissions to put in the digest.
  - FormatSubmission is a functon that takes a submision and returns a string
    containing the relevant information.
  - digest_template is a string template that will be used to create the
    digest. It must have places for the number of submissions, a plural on the
    word "submission(s)", and for a string representation of the submissions.
  - We return a string containing the summary of these submissions, intended to
    be sent to the moderators.
  """
  formatted_submissions = [FormatSubmission(sub) for sub in submissions]
  if len(submissions) != 1:
    plural = "s"
  else:
    plural = ""
  summary = "\n\n".join(formatted_submissions)
  digest = digest_template % (len(formatted_submissions), plural, summary)
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
  if DRY_RUN:
    # The list of things the bot would have expired is not in the moderation
    # log because no changes were actually made. Instead, include the whole
    # list in the digest.
    modified_digest = MakeDigest(
        modified_submissions,
        (lambda sub: "#%d: [%s](%s) (%s)" %
                     (sub.rank, sub.title, sub.permalink, sub.list_price)),
        u"Marked %d submission%s as expired:\n\n%s")
  else:
    # Just tell the mods to look at the mod log to see what was expired.
    if len(modified_submissions) != 1:
      plural = "s"
    else:
      plural = ""
    modified_digest = ("Marked %d submission%s as expired. See the "
        "[moderation log]"
        "(http://www.reddit.com/r/FreeEBOOKS/about/log/?mod=expired_link_bot) "
        "for details." % (len(modified_submissions), plural))
  needs_review_digest = MakeDigest(
      needs_review_submissions,
      (lambda sub: "#%d: ([direct link](%s)) [%s](%s)" %
                   (sub.rank, sub.url, sub.title, sub.permalink)),
      "Human review needed for %d new submission%s:\n\n%s")

  r.send_message(DIGEST_RECIPIENT, "Bot Digest",
      modified_digest + "\n\n" + needs_review_digest)

if __name__ == "__main__":
  ProcessCommandLine()

  # useragent string
  r = praw.Reddit("/r/FreeEbooks expired-link-marking bot "
                  "by /u/penguinland v. 2.1")
  r.login(USERNAME, PASSWORD)

  RunIteration(r)
