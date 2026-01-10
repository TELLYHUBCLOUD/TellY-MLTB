"""
IMDB and TMDB Integration Module for Auto Rename Feature
Provides Metadata fetching for movies and TV series
"""

from logging import getLogger
from urllib.parse import quote_plus

import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

LOGGER = getLogger(__name__)


def get_poster(query):
    """
    Fetch IMDB information for a given title

    Args:
        query (str): Title to search (can include year)

    Returns:
        dict: IMDB data with keys: title, year, rating, genres, poster
        None: If lookup fails
    """
    if not query or not query.strip():
        return None

    # If BeautifulSoup is not available, skip IMDB lookup gracefully
    if BeautifulSoup is None:
        LOGGER.warning("bs4 (BeautifulSoup) not installed; skipping IMDB lookup")
        return None

    try:
        # Clean the query
        query = query.strip()

        # Search IMDB
        search_url = (
            f"https://www.imdb.com/find?q={quote_plus(query)}&s=tt&ttype=ft,tv"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code != 200:
            LOGGER.warning(
                f"IMDB search failed with status code: {response.status_code}"
            )
            return None

        soup = BeautifulSoup(response.content, "html.parser")

        # Find first result
        result = soup.find("section", {"data-testid": "find-results-section-title"})
        if not result:
            LOGGER.warning(f"No IMDB results found for: {query}")
            return None

        first_result = result.find("a")
        if not first_result or not first_result.get("href"):
            return None

        # Get IMDB ID
        imdb_id = first_result["href"].split("/title/")[1].split("/")[0]

        # Fetch title page
        title_url = f"https://www.imdb.com/title/{imdb_id}/"
        response = requests.get(title_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, "html.parser")

        # Extract title
        title_elem = soup.find("h1", {"data-testid": "hero__primary-text"})
        title = title_elem.text.strip() if title_elem else query

        # Extract year
        year = ""
        year_elem = soup.find(
            "a", {"href": lambda x: x and "/releaseinfo" in x if x else False}
        )
        if year_elem:
            year = year_elem.text.strip()

        # Extract rating
        rating = ""
        rating_elem = soup.find(
            "span", {"class": lambda x: x and "sc-" in x if x else False}
        )
        if rating_elem and rating_elem.text:
            try:
                rating_value = rating_elem.text.strip()
                if rating_value.replace(".", "").isdigit():
                    rating = rating_value
            except:
                pass

        # Extract genres
        genres = ""
        genre_section = soup.find("div", {"data-testid": "genres"})
        if genre_section:
            genre_links = genre_section.find_all("a")
            genre_list = [g.text.strip() for g in genre_links]
            genres = ", ".join(genre_list)

        # Extract poster
        poster = ""
        poster_elem = soup.find(
            "img", {"class": lambda x: x and "ipc-image" in x if x else False}
        )
        if poster_elem and poster_elem.get("src"):
            poster = poster_elem["src"]

        imdb_data = {
            "title": title,
            "year": year,
            "rating": rating,
            "genres": genres,
            "poster": poster,
        }

        LOGGER.info(f"IMDB data fetched successfully for: {title} ({year})")
        return imdb_data

    except requests.exceptions.Timeout:
        LOGGER.error(f"IMDB lookup timeout for: {query}")
        return None
    except requests.exceptions.RequestException as e:
        LOGGER.error(f"IMDB lookup request error for {query}: {e}")
        return None
    except Exception as e:
        LOGGER.error(f"Error fetching IMDB data for {query}: {e}")
        return None

def get_tmdb_result(query, api_key, thumb_format="poster"):
    if not query or not api_key:
        return None

    try:
        # Search
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={quote_plus(query)}"
        response = requests.get(search_url, timeout=10)
        if response.status_code != 200:
            return None

        data = response.json()
        if not data.get("results"):
            return None

        result = data["results"][0]
        media_type = result.get("media_type")
        id_ = result.get("id")

        # Get details
        details_url = f"https://api.themoviedb.org/3/{media_type}/{id_}?api_key={api_key}"
        response = requests.get(details_url, timeout=10)
        if response.status_code != 200:
            return None

        details = response.json()

        title = details.get("title") or details.get("name")
        year = details.get("release_date") or details.get("first_air_date") or ""
        year = year.split("-")[0] if year else ""
        rating = details.get("vote_average", "")
        genres = ", ".join([g["name"] for g in details.get("genres", [])])

        poster_path = details.get("poster_path")
        backdrop_path = details.get("backdrop_path")

        image_url = ""
        if thumb_format == "backdrop" and backdrop_path:
            image_url = f"https://image.tmdb.org/t/p/original{backdrop_path}"
        elif poster_path:
            image_url = f"https://image.tmdb.org/t/p/original{poster_path}"
        elif backdrop_path: # Fallback
            image_url = f"https://image.tmdb.org/t/p/original{backdrop_path}"

        return {
            "title": title,
            "year": year,
            "rating": str(rating),
            "genres": genres,
            "poster": image_url
        }
    except Exception as e:
        LOGGER.error(f"TMDB error: {e}")
        return None
