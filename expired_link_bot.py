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
"""

import praw
import re
import time
import urllib2

expired_flair = "Expired"  # Flair on /r/FreeEbooks

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
  if url[:22] == "http://www.amazon.com/":
    return r'\s+class="priceLarge"\s*>([^<]*)<'
  # Add other matches here
  return ""

def CheckSubmissions(subreddit):
  """
  Given a subreddit, marks expired links and returns a list of the submissions
  that were marked.
  """
  modified_submissions = []

  for submission in subreddit.get_hot(limit=200):
    # Skip anything already marked as expired.
    if submission.link_flair_text == expired_flair:
      continue

    price_selector = GetPriceSelector(submission.url)
    if not price_selector:
      # Submission is a website where we don't know how to find the price
      continue

    try:
      # We sleep here to ensure that we send websites at most 1 qps.
      time.sleep(1)

      # Get the contents of the webpage about this ebook.
      response = urllib2.urlopen(submission.url)
      price = re.search(price_selector, response.read()).group(1).strip()
    except:
      print "Unable to download/parse URL:"
      print submission.url
      continue

    # This next line is a little hard for non-Python people to read. It's
    # asking whether any nonzero digit is contained in the price.
    if not any(digit in price for digit in "123456789"):
      continue  # It's still free!

    # If we get here, this submission is no longer free. Make a comment
    # explaining this, then set the flair to expired.
    submission.add_comment(expired_message % (price, submission.permalink))
    subreddit.set_flair(submission, expired_flair)
    submission.list_price = price  # Store this to put in the digest later.
    modified_submissions.append(submission)
  return modified_submissions

def SendDigest(modified_submissions, r):
  """
  Given a list of modified submissions and a reddit object that can send
  modmail, sends a summary of the modified submissions to the moderators.
  """
  formatted_submissions = [
      "[%s](%s) (%s)" % (sub.title, sub.permalink, sub.list_price)
      for sub in modified_submissions]
  digest = ("Marked %d submission(s) as expired:\n\n%s" %
            (len(formatted_submissions), "\n\n".join(formatted_submissions)))
  r.send_message("/r/FreeEbooks", "Bot Digest", digest)

def Main():
  # useragent string
  r = praw.Reddit("/r/FreeEbooks expired-link-marking bot "
                  "by /u/penguinland v. 1.0")

  # Remember to use the actual password when updating the version that actually
  # gets run!
  r.login("expired_link_bot", "password goes here!")  # username, password

  subreddit = r.get_subreddit('freeebooks')
  #subreddit = r.get_subreddit('chtorrr')

  modified_submissions = CheckSubmissions(subreddit)
  if len(modified_submissions) > 0:
    SendDigest(modified_submissions, r)

if __name__ == "__main__":
  Main()
