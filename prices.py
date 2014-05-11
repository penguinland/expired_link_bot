#!/usr/bin/env python

"""
Helper functions for obtaining the prices of ebooks from various sources.
"""

import re
import sys
import time
import urllib2

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
                     "https://www.amazon.com/",
                     "http://amzn.com/",
                     "https://amzn.com/",
                     "http://www.amazon.co.uk/",
                     "https://www.amazon.co.uk/",
                     "http://www.amazon.ca/",
                     "https://www.amazon.ca/")):
    return r'\s+class="priceLarge"\s*>([^<]*)<'
  if url.startswith(("http://www.smashwords.com/",
                     "https://www.smashwords.com/")):
    # If the price is listed, it follows a "Price:" but if the price is "You
    # set the price!" then it is not. Do not use parentheses to group the
    # "Price:" together, as that will put the price itself in the wrong group
    # when the regex matches.
    return r'class="panel-title text-center">\s*P?r?i?c?e?:?([^<]*)<'
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
