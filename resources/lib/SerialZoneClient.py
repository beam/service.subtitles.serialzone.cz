# -*- coding: utf-8 -*-

from utilities import log, get_file_size, get_current_episode_first_air_date
import urllib, re, os, copy, xbmc, xbmcgui
import HTMLParser
from usage_stats import results_with_stats, mark_start_time

class SerialZoneClient(object):

	def __init__(self,addon):
		self.server_url = "http://www.serialzone.cz"
		self.addon = addon
		self._t = addon.getLocalizedString
		mark_start_time()

	def download(self,link):

		dest_dir = os.path.join(xbmc.translatePath(self.addon.getAddonInfo('profile').decode("utf-8")), 'temp')
		dest = os.path.join(dest_dir, "download.zip")

		log(__name__,'Downloading subtitles from %s' % link)
		res = urllib.urlopen(link)
		subtitles_data = res.read()

		log(__name__,'Saving to file %s' % dest)
		zip_file = open(dest,'wb')
		zip_file.write(subtitles_data)
		zip_file.close()

		return dest

	def normalize_input_title(self, title):
		if self.addon.getSetting("search_title_in_brackets") == "true":
			log(__name__, "Searching title in brackets - %s" % title)
			search_second_title = re.match(r'.+ \((.{3,})\)',title)
			if search_second_title and not re.search(r'^[\d]{4}$',search_second_title.group(1)): title = search_second_title.group(1)

		if re.search(r', The$',title,re.IGNORECASE):
			log(__name__, "Swap The - %s" % title)
			title =  "The " + re.sub(r'(?i), The$',"", title) # normalize The

		if self.addon.getSetting("try_cleanup_title") == "true":
			log(__name__, "Title cleanup - %s" % title)
			title = re.sub(r"(\[|\().+?(\]|\))","",title) # remove [xy] and (xy)

		return title.strip()

	def search(self,item):

		if item['mansearch']:
			title = item['mansearchstr']
			dialog = xbmcgui.Dialog()
			item['season'] = dialog.numeric(0, self._t(32111), item['season'])
			item['episode'] = dialog.numeric(0, self._t(32112), item['episode'])
		else:
			title = self.normalize_input_title(item['tvshow'])
			if self.addon.getSetting("ignore_articles") == "true" and re.match(r'^The ',title,re.IGNORECASE):
				log(__name__, "Ignoring The in Title")
				title = re.sub(r'(?i)^The ',"", title)

		if not title or not item['season'] or not item['episode']:
			xbmc.executebuiltin("XBMC.Notification(%s,%s,5000,%s)" % (
						self.addon.getAddonInfo('name'), self._t(32110),
						os.path.join(xbmc.translatePath(self.addon.getAddonInfo('path')).decode("utf-8"),'icon.png')
			))
			log(__name__, ["Input validation error", title, item['season'], item['episode']])
			return results_with_stats(None, self.addon, title, item)

		tvshow_url = self.search_show_url(title)
		if tvshow_url == None: return results_with_stats(None, self.addon, title, item)

		file_size = get_file_size(item['file_original_path'], item['rar'])
		log(__name__, "File size: %s" % file_size)

		found_season_subtitles = self.search_season_subtitles(tvshow_url,item['season'])
		log(__name__, ["Season filter", found_season_subtitles])

		episode_subtitle_list = self.filter_episode_from_season_subtitles(found_season_subtitles,item['season'],item['episode'])
		log(__name__, ["Episode filter", episode_subtitle_list])
		if episode_subtitle_list == None: return results_with_stats(None, self.addon, title, item)

		lang_filetred_episode_subtitle_list = self.filter_subtitles_by_language(item['3let_language'], episode_subtitle_list)
		log(__name__, ["Language filter", lang_filetred_episode_subtitle_list])
		if lang_filetred_episode_subtitle_list == None: return results_with_stats(None, self.addon, title, item)

		max_down_count = self.detect_max_download_stats(lang_filetred_episode_subtitle_list)

		result_subtitles = []
		for episode_subtitle in lang_filetred_episode_subtitle_list['versions']:

			print_out_filename = episode_subtitle['rip'] + " by " + episode_subtitle['author']
			if episode_subtitle['notes']: print_out_filename += " (" + episode_subtitle['notes'] + ")"

			result_subtitles.append({
				'filename': HTMLParser.HTMLParser().unescape(print_out_filename),
				'link': episode_subtitle['link'],
				'lang': episode_subtitle['lang'],
				'rating': str(episode_subtitle['down_count']*5/max_down_count) if max_down_count > 0 else "0",
				'sync': (episode_subtitle['file_size'] == file_size and file_size > 0),
				'lang_flag': xbmc.convertLanguage(episode_subtitle['lang'],xbmc.ISO_639_1),
			})

		log(__name__,["Search result", result_subtitles])

		return results_with_stats(result_subtitles, self.addon, title, item)


	def filter_episode_from_season_subtitles(self, season_subtitles, season, episode):
		for season_subtitle in season_subtitles:
			if (season_subtitle['episode'] == int(episode) and season_subtitle['season'] == int(season)):
				return season_subtitle
		return None

	def filter_subtitles_by_language(self, set_languages, subtitles_list):
		if not set_languages: return subtitles_list

		log(__name__, ['Filter by languages', set_languages])
		filter_subtitles_list = []
		for subtitle in subtitles_list['versions']:
			if xbmc.convertLanguage(subtitle['lang'],xbmc.ISO_639_2) in set_languages:
				filter_subtitles_list.append(subtitle)

		if not filter_subtitles_list:
			if "cze" not in set_languages and "slo" not in set_languages:
				dialog = xbmcgui.Dialog()
				if dialog.yesno(self.addon.getAddonInfo('name'), self._t(32100), self._t(32101)):
					xbmc.executebuiltin("Dialog.Close(subtitlesearch)")
					xbmc.executebuiltin("PlayerControl(Stop)")
					xbmc.executebuiltin("ActivateWindowAndFocus(playersettings,-96,0,-67,0)")
			return None
		else:
			filter_results_list = copy.deepcopy(subtitles_list)
			filter_results_list['versions'] = filter_subtitles_list
			return filter_results_list

	def detect_max_download_stats(self, episode_subtitle_list):
		max_down_count = 0
		for episode_subtitle in episode_subtitle_list['versions']:
			if max_down_count < episode_subtitle['down_count']:
				max_down_count = episode_subtitle['down_count']

		log(__name__,"Max download count: %s" % max_down_count)
		return max_down_count

	def search_show_url(self,title):
		log(__name__,"Starting search by TV Show: %s" % title)
		if not title: return None

		url_search = self.server_url + "/hledani/?" + urllib.urlencode({ "co" : title, "kde" : "serialy" })
		log(__name__,"Search URL: " + url_search)
		res = urllib.urlopen(url_search)

		log(__name__, "Parsing tv show results")
		found_tv_shows = []
		try:
			res_body = re.search("<div class=\"column4 wd2 fl-left\">(.+?)<div class=\"cl12px fl-left\"></div>",res.read(), re.IGNORECASE | re.DOTALL).group(1)
		except:
			res_body = res.read()

		for row in re.findall('<li>(.+?)</li>', res_body, re.IGNORECASE | re.DOTALL):
			if re.search("\/serial\/", row):
				show = {}
				show_reg_exp = re.compile("<a href=\"(.+?)\">(.+?) <span class=\"vysilani\">\((.+?)\)</span></a><br />(.+?)$")
				show['url'], show['title'], show['years'], show['orig_title'] = re.search(show_reg_exp, row).groups()
				show['years'] = show['years'].replace("&#8211;", "-")
				found_tv_shows.append(show)

		first_air_date = None
		if self.addon.getSetting("filter_shows_by_year") == "true" and len(found_tv_shows) > 1:
			log(__name__, "Getting first air date")
			first_air_date = get_current_episode_first_air_date()

		if first_air_date:
			log(__name__, "Filtr by year")
			filtered_found_tv_shows = []
			for found_tv_show in found_tv_shows:
				year_reg_exp = re.compile("^([\d]{4})(|-)([\d]{4}|[\?]{4}|$)")
				year_from, year_sep , year_to = re.search(year_reg_exp, found_tv_show["years"]).groups()
				if year_to == "????":
					if int(year_from) <= first_air_date.year: filtered_found_tv_shows.append(found_tv_show)
				elif year_to == '':
					if int(year_from) == first_air_date.year: filtered_found_tv_shows.append(found_tv_show)
				else:
					if int(year_from) <= first_air_date.year and int(year_to) >= first_air_date.year: filtered_found_tv_shows.append(found_tv_show)

			if len(filtered_found_tv_shows) > 0 and not len(filtered_found_tv_shows) == len(found_tv_shows):
				log(__name__, "TV show filtered by year")
				found_tv_shows = filtered_found_tv_shows

		if (len(found_tv_shows) == 0):
			log(__name__,"TV Show not found")
			return None
		elif (len(found_tv_shows) == 1):
			log(__name__,"One TV Show found, autoselecting")
			tvshow_url = found_tv_shows[0]['url']
		else:
			log(__name__,"More TV Shows found, user dialog for select")
			menu_dialog = []
			for found_tv_show in found_tv_shows:
				if (found_tv_show['orig_title'] == found_tv_show['title']):
					dialog_item_title = found_tv_show['title'] + " - " + found_tv_show['years']
				else:
					dialog_item_title = found_tv_show['title'] + " / " + found_tv_show['orig_title'] + " - " + found_tv_show['years']
				menu_dialog.append(dialog_item_title)

			dialog = xbmcgui.Dialog()
			found_tv_show_id = dialog.select(self._t(32003), menu_dialog)
			if (found_tv_show_id == -1): return None
			tvshow_url = found_tv_shows[found_tv_show_id]['url']

		log(__name__,"Selected show URL: " + tvshow_url)
		return tvshow_url

	def search_season_subtitles(self, show_url, show_series):
		res = urllib.urlopen(show_url + "titulky/" + show_series + "-rada/")
		if not res.getcode() == 200: return []
		subtitles = []
		for html_episode in re.findall('<div .+? class=\"sub\-line .+?>(.+?)</div></div></div></div>',res.read(), re.IGNORECASE | re.DOTALL):
			subtitle = {}
			for html_subtitle in html_episode.split("<div class=\"sb1\">"):
				show_numbers = re.search("<div class=\"sub-nr\">(.+?)</div>",html_subtitle)
				if not show_numbers == None:
					subtitle['season'], subtitle['episode'] = re.search("([0-9]+)x([0-9]+)", show_numbers.group(1)).groups()
					subtitle['season'] = int(subtitle['season'])
					subtitle['episode'] = int(subtitle['episode'])
					subtitle['versions'] = []
				else:
					subtitle_version = {}
					subtitle_version['lang'] = re.search("<div class=\"sub-info-menu sb-lang\">(.+?)</div>", html_subtitle).group(1).upper()
					if subtitle_version['lang'] == "CZ": subtitle_version['lang'] = "Czech"
					if subtitle_version['lang'] == "SK": subtitle_version['lang'] = "Slovak"
					subtitle_version['link'] = re.search("<a href=\"(.+?)\" .+? class=\"sub-info-menu sb-down\">",html_subtitle).group(1)
					subtitle_version['author'] = re.sub("<[^<]+?>", "",(re.search("<div class=\"sub-info-auth\">(.+?)</div>",html_subtitle).group(1))).decode("utf-8",'replace')
					subtitle_version['rip'] = re.search("<div class=\"sil\">Verze / Rip:</div><div class=\"sid\"><b>(.+?)</b>",html_subtitle).group(1).decode("utf-8",'replace')
					try:
						subtitle_version['notes'] = re.search("<div class=\"sil\">Poznámka:</div><div class=\"sid\">(.+?)</div>",html_subtitle).group(1).decode("utf-8",'replace')
					except:
						subtitle_version['notes'] = None
					subtitle_version['down_count'] = int(re.search("<div class=\"sil\">Počet stažení:</div><div class=\"sid2\">(.+?)x</div>",html_subtitle).group(1))
					try:
						subtitle_version['file_size'] = re.search("<span class=\"fl-right\" title=\".+\">\((.+?) b\)</span>",html_subtitle).group(1)
						subtitle_version['file_size'] = int(subtitle_version['file_size'].replace(" ",""))
					except:
						subtitle_version['file_size'] = None
					subtitle['versions'].append(subtitle_version)
			subtitles.append(subtitle)
		return subtitles
