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
- If you run this bot as a cron job, remember to set the PYTHONPATH up
  correctly in your crontab as well!
"""

import praw
import re
import time
import urllib2

TESTING = True  # Set to false for the real version.

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

def GetPriceSelector(url):
  """
  Given a string containing a URL, if it matches something where we know how to
  find the price, return a string containing the regular expression that will
  have the price in its first group. If we don't know how to find the price on
  this URL, return the empty string.
  """
  if (url.startswith("http://www.amazon.com/") or
      # Note that amazon.co.uk doesn't work yet because it's using a
      # non-UTF8 encoding for the pound symbol (possibly Latin-1 extended
      # ASCII?), and that's messing up the string formatting in
      # comments/messages. I need to figure out how to detect and deal with
      # this format.
      #url.startswith("http://www.amazon.co.uk/") or
      url.startswith("http://www.amazon.ca/")):
    return r'\s+class="priceLarge"\s*>([^<]*)<'
  if url.startswith("https://www.smashwords.com/"):
    return r'class="panel-title text-center">\s*Price:([^<]*)<'
  if url.startswith("http://www.barnesandnoble.com/"):
    return r'itemprop="price" data-bntrack="Price" data-bntrack-event="click">([^<]*)<'
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

    # Get the contents of the webpage about this ebook.
    html = urllib2.urlopen(url).read()
    price = re.search(price_selector, html).group(1).strip()
    return price
  except:
    print "Unable to download/parse URL:"
    print url
    return ""

def CheckSubmissions(subreddit):
  """
  Given a subreddit, marks expired links and returns a list of the submissions
  that were marked.
  """
  modified_submissions = []

  for submission in subreddit.get_hot(limit=200):
    # Skip anything already marked as expired.
    if submission.link_flair_css_class == expired_css_class:
      continue

    # The price might be the empty string if we're unable to get the real price.
    price = GetPrice(submission.url)
    # This next line is a little hard for non-Python people to read. It's
    # asking whether any nonzero digit is contained in the price.
    if not any(digit in price for digit in "123456789"):
      continue  # Either we're unable to get the price, or it's still free

    # If we get here, this submission is no longer free. Make a comment
    # explaining this and set the flair to expired.
    if not TESTING:
      submission.add_comment(expired_message % (price, submission.permalink))
      subreddit.set_flair(submission, expired_flair, expired_css_class)
    submission.list_price = price  # Store this to put in the digest later.
    modified_submissions.append(submission)
  return modified_submissions

def MakeDigest(modified_submissions):
  """
  Given a list of modified submissions, returns a string containing a summary
  of the modified submissions, intended to be sent to the moderators.
  """
  formatted_submissions = [
      u"[%s](%s) (%s)" % (sub.title, sub.permalink, sub.list_price)
      for sub in modified_submissions]
  digest = (u"Marked %d submission(s) as expired:\n\n%s" %
            (len(formatted_submissions), u"\n\n".join(formatted_submissions)))
  return digest

def Main():
  # useragent string
  r = praw.Reddit("/r/FreeEbooks expired-link-marking bot "
                  "by /u/penguinland v. 1.1")

  # Remember to use the actual password when updating the version that actually
  # gets run!
  r.login("expired_link_bot", "password goes here")  # username, password

  if TESTING:
    subreddit = r.get_subreddit("chtorrr")  # Testing data is in /r/chtorrr
  else:
    subreddit = r.get_subreddit("freeebooks")  # Real data is in /r/FreeEbooks
  modified_submissions = CheckSubmissions(subreddit)

  if len(modified_submissions) > 0:
    digest = MakeDigest(modified_submissions)
    if TESTING:
      recipient = "penguinland"  # Send test digests only to me.
    else:
      recipient = "/r/FreeEbooks"  # Send the real digest to the mods
    r.send_message(recipient, "Bot Digest", digest)

if __name__ == "__main__":
  Main()
