#!/usr/bin/env python3
"""
Sonarr Custom Script: Season Pack Detector

This script detects when a complete season has been imported where all episodes
share the same release group, source, and resolution. When detected, it marks
the season as a "Season Pack" to prevent duplicate downloads.

Usage: Configure in Sonarr under Settings > Connect > Custom Script
       Select "On Import" trigger

Environment variables provided by Sonarr:
- sonarr_eventtype: Type of event (Download, Test, etc.)
- sonarr_series_id: Series ID
- sonarr_series_title: Series title
- sonarr_episodefile_id: Episode file ID
- sonarr_episodefile_seasonnumber: Season number
- sonarr_episodefile_quality: Quality profile
- sonarr_episodefile_releasegroup: Release group
- sonarr_episodefile_scenename: Scene name
"""

import os
import sys
import json
import logging
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SonarrAPI:
    """Sonarr API client"""

    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        }

    def _request(self, endpoint: str, method: str = 'GET', data: Optional[Dict] = None) -> Dict:
        """Make API request to Sonarr"""
        url = urljoin(f"{self.url}/api/v3/", endpoint.lstrip('/'))

        req = Request(url, headers=self.headers, method=method)
        if data:
            req.data = json.dumps(data).encode('utf-8')

        try:
            with urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode('utf-8'))
        except HTTPError as e:
            logger.error(f"HTTP error {e.code}: {e.reason}")
            raise
        except URLError as e:
            logger.error(f"URL error: {e.reason}")
            raise

    def get_episode_files_by_series_season(self, series_id: int, season_number: int) -> List[Dict]:
        """Get all episode files for a series season"""
        files = self._request(f"episodefile?seriesId={series_id}")
        return [f for f in files if f.get('seasonNumber') == season_number]

    def get_series(self, series_id: int) -> Dict:
        """Get series information"""
        return self._request(f"series/{series_id}")

    def get_episode_file(self, file_id: int) -> Dict:
        """Get episode file details"""
        return self._request(f"episodefile/{file_id}")

    def update_episode_file(self, file_id: int, data: Dict) -> Dict:
        """Update episode file"""
        return self._request(f"episodefile/{file_id}", method='PUT', data=data)

    def add_tag_to_episode_file(self, file_id: int, tag: str) -> None:
        """Add a tag to an episode file"""
        file_data = self.get_episode_file(file_id)

        # Get or create tag
        tags = self._request("tag")
        tag_obj = next((t for t in tags if t['label'].lower() == tag.lower()), None)

        if not tag_obj:
            tag_obj = self._request("tag", method='POST', data={'label': tag})

        # Add tag to file if not already present
        if tag_obj['id'] not in file_data.get('tags', []):
            file_data['tags'] = file_data.get('tags', []) + [tag_obj['id']]
            self.update_episode_file(file_id, file_data)


def extract_quality_info(episode_file: Dict) -> Dict[str, str]:
    """Extract quality, source, and resolution from episode file"""
    quality = episode_file.get('quality', {}).get('quality', {})
    media_info = episode_file.get('mediaInfo', {})

    return {
        'source': quality.get('source', 'Unknown'),
        'resolution': quality.get('resolution', 'Unknown'),
        'release_group': episode_file.get('releaseGroup', 'Unknown'),
    }


def is_season_complete(api: SonarrAPI, series_id: int, season_number: int) -> bool:
    """Check if all episodes in the season have been downloaded"""
    series = api.get_series(series_id)

    # Find the season in series data
    season_data = next(
        (s for s in series.get('seasons', []) if s.get('seasonNumber') == season_number),
        None
    )

    if not season_data:
        logger.warning(f"Season {season_number} not found in series data")
        return False

    # Get episode files for this season
    episode_files = api.get_episode_files_by_series_season(series_id, season_number)

    # Count downloaded episodes (each file may contain multiple episodes)
    downloaded_episodes = set()
    for file in episode_files:
        downloaded_episodes.update(file.get('episodeIds', []))

    total_episodes = season_data.get('statistics', {}).get('totalEpisodeCount', 0)
    downloaded_count = len(downloaded_episodes)

    logger.info(f"Season {season_number}: {downloaded_count}/{total_episodes} episodes")

    return downloaded_count == total_episodes and total_episodes > 0


def check_uniform_quality(episode_files: List[Dict]) -> Optional[Dict[str, str]]:
    """
    Check if all episode files have the same release group, source, and resolution.
    Returns the uniform attributes if true, None otherwise.
    """
    if not episode_files:
        return None

    # Extract quality info from first file
    first_file_quality = extract_quality_info(episode_files[0])

    # Check all other files match
    for file in episode_files[1:]:
        file_quality = extract_quality_info(file)
        if file_quality != first_file_quality:
            logger.info(f"Quality mismatch: {file_quality} != {first_file_quality}")
            return None

    return first_file_quality


def main():
    """Main script execution"""
    # Sonarr is always on localhost in the same container
    sonarr_url = 'http://localhost:8989'
    sonarr_api_key = os.environ.get('SONARR__AUTH__APIKEY')

    if not sonarr_api_key:
        logger.error("SONARR__AUTH__APIKEY environment variable not set")
        sys.exit(1)

    # Get event information from Sonarr
    event_type = os.environ.get('sonarr_eventtype')
    series_id = os.environ.get('sonarr_series_id')
    series_title = os.environ.get('sonarr_series_title')
    season_number = os.environ.get('sonarr_episodefile_seasonnumber')
    episode_file_id = os.environ.get('sonarr_episodefile_id')

    # Handle test event
    if event_type == 'Test':
        logger.info("Test event received - script is configured correctly")
        sys.exit(0)

    # Validate required environment variables
    if not all([series_id, season_number, episode_file_id]):
        logger.error("Missing required Sonarr environment variables")
        sys.exit(1)

    try:
        series_id = int(series_id)
        season_number = int(season_number)
        episode_file_id = int(episode_file_id)
    except ValueError:
        logger.error("Invalid numeric values in environment variables")
        sys.exit(1)

    logger.info(f"Processing import for {series_title} S{season_number:02d}")

    # Initialize API client
    api = SonarrAPI(sonarr_url, sonarr_api_key)

    try:
        # Check if season is complete
        if not is_season_complete(api, series_id, season_number):
            logger.info("Season is not yet complete")
            sys.exit(0)

        # Get all episode files for the season
        episode_files = api.get_episode_files_by_series_season(series_id, season_number)

        if not episode_files:
            logger.warning("No episode files found for season")
            sys.exit(0)

        # Check if all files have uniform quality attributes
        uniform_quality = check_uniform_quality(episode_files)

        if not uniform_quality:
            logger.info("Files do not have uniform quality attributes")
            sys.exit(0)

        # Season is complete with uniform quality - mark as season pack
        logger.info(
            f"Season pack detected: {uniform_quality['release_group']} "
            f"{uniform_quality['source']} {uniform_quality['resolution']}"
        )

        # Tag all episode files in the season
        for file in episode_files:
            api.add_tag_to_episode_file(file['id'], 'season-pack')
            logger.info(f"Tagged episode file {file['id']} as season-pack")

        logger.info(f"Successfully marked season {season_number} as season pack")

    except Exception as e:
        logger.error(f"Error processing season pack detection: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
