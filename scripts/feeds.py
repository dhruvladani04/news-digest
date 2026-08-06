"""
Feed registry.

Each feed: (name, url, sector, tier)
  tier 1 = wire service / primary source / peer-reviewed  (most trusted)
  tier 2 = established outlet with editorial standards
  tier 3 = specialist blog / aggregator / community

Tier feeds directly into ranking -- see rank.py TIER_WEIGHT.

To add a feed: append to the right sector block and re-run
    python scripts/validate_feeds.py
which tells you immediately whether the URL is good.
"""

SECTORS = [
    {"id": "ai_tech",       "name": "AI & Tech",
     "blurb": "Models, chips, platforms and the companies building them"},
    {"id": "finance",       "name": "Finance & Markets",
     "blurb": "Macro, equities, central banks, crypto"},
    {"id": "geopolitics",   "name": "Geopolitics & Defense",
     "blurb": "Statecraft, conflict, trade and security"},
    {"id": "frontier",      "name": "Startups, Science & Energy",
     "blurb": "Funding, research breakthroughs, the energy transition"},
    {"id": "entertainment", "name": "Entertainment",
     "blurb": "Film, television and the comic-book universes"},
]

FEEDS = [
    # ---------------------------------------------------------------- AI & Tech
    ("Ars Technica",        "https://feeds.arstechnica.com/arstechnica/index",          "ai_tech", 2),
    ("The Verge",           "https://www.theverge.com/rss/index.xml",                   "ai_tech", 2),
    ("TechCrunch",          "https://techcrunch.com/feed/",                             "ai_tech", 2),
    ("MIT Tech Review",     "https://www.technologyreview.com/feed/",                   "ai_tech", 1),
    ("VentureBeat AI",      "https://venturebeat.com/category/ai/feed/",                "ai_tech", 3),
    ("Wired",               "https://www.wired.com/feed/rss",                           "ai_tech", 2),
    ("Engadget",            "https://www.engadget.com/rss.xml",                         "ai_tech", 3),
    ("Hacker News",         "https://hnrss.org/frontpage?points=200",                   "ai_tech", 3),
    ("Google Research",     "https://research.google/blog/rss/",                        "ai_tech", 1),
    ("OpenAI",              "https://openai.com/news/rss.xml",                          "ai_tech", 1),
    ("Hugging Face",        "https://huggingface.co/blog/feed.xml",                     "ai_tech", 2),
    ("The Register",        "https://www.theregister.com/headlines.atom",               "ai_tech", 3),

    # --------------------------------------------------------- Finance & Markets
    ("CNBC Top News",       "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "finance", 2),
    ("CNBC Markets",        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",  "finance", 2),
    ("MarketWatch",         "https://feeds.content.dowjones.io/public/rss/mw_topstories", "finance", 2),
    ("Financial Times",     "https://www.ft.com/rss/home",                              "finance", 1),
    ("Economic Times",      "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "finance", 2),
    ("Livemint Markets",    "https://www.livemint.com/rss/markets",                     "finance", 2),
    ("Business Standard",   "https://www.business-standard.com/rss/markets-106.rss",    "finance", 2),
    ("CoinDesk",            "https://www.coindesk.com/arc/outboundfeeds/rss/",          "finance", 3),
    ("Federal Reserve",     "https://www.federalreserve.gov/feeds/press_monetary.xml",  "finance", 1),
    ("Yahoo Finance",       "https://finance.yahoo.com/news/rssindex",                  "finance", 3),
    ("Reuters Business",    "https://news.google.com/rss/search?q=site:reuters.com+when:2d&hl=en-US&gl=US&ceid=US:en", "finance", 1),
    ("Moneycontrol",        "https://www.moneycontrol.com/rss/marketreports.xml",       "finance", 2),
    ("Investing.com",       "https://www.investing.com/rss/news_25.rss",                "finance", 3),

    # ----------------------------------------------------- Geopolitics & Defense
    ("BBC World",           "https://feeds.bbci.co.uk/news/world/rss.xml",              "geopolitics", 1),
    ("Al Jazeera",          "https://www.aljazeera.com/xml/rss/all.xml",                "geopolitics", 2),
    ("The Guardian World",  "https://www.theguardian.com/world/rss",                    "geopolitics", 2),
    ("Foreign Policy",      "https://foreignpolicy.com/feed/",                          "geopolitics", 2),
    ("The Diplomat",        "https://thediplomat.com/feed/",                            "geopolitics", 2),
    ("Defense News",        "https://www.defensenews.com/arc/outboundfeeds/rss/",       "geopolitics", 2),
    ("War on the Rocks",    "https://warontherocks.com/feed/",                          "geopolitics", 3),
    ("The Hindu Intl",      "https://www.thehindu.com/news/international/feeder/default.rss", "geopolitics", 2),
    ("DW News",             "https://rss.dw.com/rdf/rss-en-world",                      "geopolitics", 2),
    ("NPR World",           "https://feeds.npr.org/1004/rss.xml",                       "geopolitics", 1),
    ("France 24",           "https://www.france24.com/en/rss",                          "geopolitics", 2),
    ("Reuters World",       "https://news.google.com/rss/search?q=site:reuters.com+world+when:2d&hl=en-US&gl=US&ceid=US:en", "geopolitics", 1),
    ("AP News",             "https://news.google.com/rss/search?q=site:apnews.com+when:2d&hl=en-US&gl=US&ceid=US:en", "geopolitics", 1),

    # ----------------------------------------------- Startups, Science & Energy
    ("TechCrunch Startups", "https://techcrunch.com/category/startups/feed/",            "frontier", 2),
    ("Crunchbase News",     "https://news.crunchbase.com/feed/",                        "frontier", 2),
    ("Inc42",               "https://inc42.com/feed/",                                  "frontier", 3),
    ("Nature News",         "https://www.nature.com/nature.rss",                        "frontier", 1),
    ("Science Daily",       "https://www.sciencedaily.com/rss/top/science.xml",         "frontier", 2),
    ("Phys.org",            "https://phys.org/rss-feed/",                               "frontier", 2),
    ("NASA",                "https://www.nasa.gov/news-release/feed/",                  "frontier", 1),
    ("Ars Science",         "https://feeds.arstechnica.com/arstechnica/science",        "frontier", 2),
    ("Carbon Brief",        "https://www.carbonbrief.org/feed/",                        "frontier", 2),
    ("Canary Media",        "https://www.canarymedia.com/feed",                         "frontier", 2),
    ("IEEE Spectrum",       "https://spectrum.ieee.org/feeds/feed.rss",                 "frontier", 2),
    ("Quanta Magazine",     "https://api.quantamagazine.org/feed/",                     "frontier", 1),

    # ----------------------------------------------------------- Entertainment
    ("Variety",             "https://variety.com/feed/",                                "entertainment", 2),
    ("Hollywood Reporter",  "https://www.hollywoodreporter.com/feed/",                  "entertainment", 2),
    ("Deadline",            "https://deadline.com/feed/",                               "entertainment", 2),
    ("IGN",                 "https://feeds.ign.com/ign/all",                            "entertainment", 3),
    ("ScreenRant",          "https://screenrant.com/feed/",                             "entertainment", 3),
    ("Collider",            "https://collider.com/feed/",                               "entertainment", 3),
    ("/Film",               "https://www.slashfilm.com/feed/",                          "entertainment", 3),
    ("CBR",                 "https://www.cbr.com/feed/",                                "entertainment", 3),
    ("Entertainment Weekly","https://ew.com/feed/",                                     "entertainment", 3),
    ("Empire",              "https://www.empireonline.com/rss/movies/news/",            "entertainment", 3),
    ("The Wrap",            "https://www.thewrap.com/feed/",                            "entertainment", 3),
    ("Gizmodo io9",         "https://gizmodo.com/feed",                                 "entertainment", 3),
    # --- added after the first validation run: the block above is heavily
    # TLS-blocked on some consumer networks, so these are independent backups.
    ("Marvel/DC wire",      "https://news.google.com/rss/search?q=%22Marvel+Studios%22+OR+%22DC+Studios%22+OR+%22James+Gunn%22+when:2d&hl=en-US&gl=US&ceid=US:en", "entertainment", 2),
    ("Film & TV wire",      "https://news.google.com/rss/search?q=(movie+OR+series+OR+streaming)+(trailer+OR+%22release+date%22+OR+casting)+when:2d&hl=en-US&gl=US&ceid=US:en", "entertainment", 3),
    ("Rolling Stone",       "https://www.rollingstone.com/feed/",                       "entertainment", 3),
    ("Den of Geek",         "https://www.denofgeek.com/feed/",                          "entertainment", 3),
    ("Bleeding Cool",       "https://bleedingcool.com/feed/",                           "entertainment", 3),
    ("ComicBook.com",       "https://comicbook.com/feed/",                              "entertainment", 3),
    ("AV Club",             "https://www.avclub.com/rss",                               "entertainment", 3),
    ("Polygon",             "https://www.polygon.com/rss/index.xml",                    "entertainment", 3),
    ("BBC Entertainment",   "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml", "entertainment", 1),
]


def by_sector(sector_id):
    return [f for f in FEEDS if f[2] == sector_id]


def sector_name(sector_id):
    for s in SECTORS:
        if s["id"] == sector_id:
            return s["name"]
    return sector_id
