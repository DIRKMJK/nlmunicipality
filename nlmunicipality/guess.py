"""Guess municipality name from user-provided location name (in Dutch)"""

import re
from pathlib import Path, PosixPath
import zipfile
import io
import shutil
import requests
import pandas as pd
import cbsodata
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from bs4 import BeautifulSoup as bs


REMOVE = [
    'the netherlands', 'nederland', 'netherlands', ' holland', 'gemeente',
    'europe', 'europa',
]
RECODE_GEM = {
    'den bosch': "'s-Hertogenbosch",
    'den haag': "'s-Gravenhage",
    'the hague': "'s-Gravenhage",
    '❌❌❌': "Amsterdam"
}
DELIMITERS = ['|', '/', '&', '(', ')']
PROV_ABBRS = {
    'CPR': 'Centraal persoonsregister',
    'Drostambt': None,
    'F.': 'Friesland',
    'Gld.': 'Gelderland',
    'Gr.': 'Groningen',
    'L.': 'Limburg',
    'NB.': 'Noord-Brabant',
    'NH.': 'Noord-Holland',
    'O.': 'Overijssel',
    'Schouwen-Duivenland': 'Zeeland',
    'U.': 'Utrecht',
    'Walcheren': 'Zeeland',
    'Z.': 'Zeeland',
    'ZH.': 'Zuid-Holland',
    'gemeente': None,
    'oud': None
}

MATCH_YEAR = 2022
THRESHOLD_FUZZY = 85
THRESHOLD_RATIO = 80

AREA_CD_URL = 'https://nl.wikipedia.org/wiki/Lijst_van_Nederlandse_netnummers'
MUNI_HISTORY_URL = 'https://www.cbs.nl/-/media/cbs/dossiers/nederland-regionaal/gemeente/gemeente-en-regionale-indelingen/overzicht-alle-gebieden.zip'
MUNI_HISTORY_WIKI_URL = 'https://nl.wikipedia.org/wiki/Lijst_van_voormalige_Nederlandse_gemeenten'

GRAVEN = r'^[\'|‘|’]*s[-| ]graven(.*?)$'
NAME_PROV = r'(.*?) \((.*?)\)'
CREATED = r'Ontstaan per ([0-9]{2})\-([0-9]{2})\-([0-9]{4})'
ENDED = r'Opgeheven per ([0-9]{2})\-([0-9]{2})\-([0-9]{4})'
RENAMED = r'Naamswijziging per ([0-9]{2})\-([0-9]{2})\-([0-9]{4})'
GM_CODE = r'GM[0-9]{4}'
POP = r' ([0-9]*) inwoner'


class GuessMunicipality():
    """Contains config and function to guess municipality"""
    def __init__(
        self,
        dir_config=None,
        ignore=None,
        remove=None,
        recode_gem=None,
        replace=None,
        threshold_fuzzy=THRESHOLD_FUZZY,
        threshold_ratio=THRESHOLD_RATIO,
        area_codes_url=AREA_CD_URL,
        match_year=MATCH_YEAR
    ):
        """
        :param dir_config: directory where to store config, if None
            config will not be stored
        :param ignore: input values that should be ignored
        :param remove: substrings that should be removed from input value
        :param recode_gem: dict of alternative spellings of municipalities
        :param replace: dict of substrings that should be replaced with
            corresponding value
        :param threshold_fuzzy: minimum score for fuzzy matches
        :param threshold_ratio: minimum percentage of population that should be
            transfered to new municipality in order to assume that the original
            municipality has merged into the new municipality
        :param area_codes_url: url of Wikipedia page with area codes
        :param match_year: year for which a match should be found

        """
        if not isinstance(dir_config, PosixPath):
            dir_config = Path(dir_config)
        self.dir_config = dir_config
        if ignore:
            self.ignore = ignore
        else:
            self.ignore = []
        if remove:
            self.remove = remove
        else:
            self.remove = REMOVE
        if recode_gem:
            self.recode_gem = recode_gem
        else:
            self.recode_gem = RECODE_GEM
        if replace:
            self.replace = replace
        else:
            self.replace = {}
        self.threshold_fuzzy = threshold_fuzzy
        self.area_codes_url = area_codes_url
        if not isinstance(match_year, int):
            match_year = int(match_year)
        self.match_year = str(match_year)
        config = self.get_config(self.dir_config)
        self.wp, self.gm, self.wb, self.replace = config
        self.threshold_ratio = threshold_ratio
        self.muni_history_cbs = self.parse_muni_history_cbs()
        self.found_results = {}
        self.wp_table_id = None
        self.kwb_table_id = None


    def get_wp_table(self):
        """Open or download place name table"""
        table_exists = False
        if self.dir_config:
            for path in self.dir_config.glob('wp*NED*.csv'):
                if re.findall(r'wp_.*?_{}\.csv'.format(self.match_year), path.stem):
                    table_exists = True
                    wp_table = pd.read_csv(path)
                    break
        if not table_exists:
            cbs_tables = cbsodata.get_table_list()
            for table in cbs_tables:
                title = table['Title']
                if title == f'Woonplaatsen in Nederland {self.match_year}':
                    self.wp_table_id = table['Identifier']
                    break
            wp_table = pd.DataFrame(cbsodata.get_data(self.wp_table_id))
            filename = f'wp_{self.wp_table_id}_{self.match_year}.csv'
            path = self.dir_config / filename
            wp_table.to_csv(path, index=False)
        return wp_table


    def get_kwb_table(self):
        """Open or download neighbourhood data table"""
        table_exists = False
        if self.dir_config:
            for path in self.dir_config.glob('kwb*NED*.csv'):
                if re.findall(r'kwb_.*?_{}\.csv'.format(self.match_year), path.stem):
                    table_exists = True
                    kwb_table = pd.read_csv(path, low_memory=False)
                    break
        if not table_exists:
            cbs_tables = cbsodata.get_table_list()
            for table in cbs_tables:
                title = table['Title']
                if title == f'Kerncijfers wijken en buurten {self.match_year}':
                    self.kwb_table_id = table['Identifier']
                    break
            kwb_table = pd.DataFrame(cbsodata.get_data(self.kwb_table_id))
            filename = f'kwb_{self.kwb_table_id}_{self.match_year}.csv'
            path = self.dir_config / filename
            kwb_table.to_csv(path, index=False)
        return kwb_table


    def get_area_codes(self):
        """Get area codes from Wikipedia"""
        area_codes = pd.DataFrame(columns=['code', 'place'])
        response = requests.get(self.area_codes_url)
        if response.status_code != 200:
            print('Failed to download area codes')
            return None
        soup = bs(response.text, 'lxml')
        table = soup.find('table')
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if cells:
                code, places = cells
                code = code.text.replace('\n', '')
                main_place = places.find('b')
                if not main_place:
                    continue
                main_place = main_place.text.split('(')[0].strip().lower()
                area_codes.loc[len(area_codes)] = [code, main_place]
        return area_codes


    def datestr_from_nl(self, datestr):
        """Convert to %Y%m%d"""
        if pd.isna(datestr) or datestr == '?':
            return None
        items = datestr.split('-')
        items.reverse()
        return ''.join(items)


    def follow_wiki(self, gm_name, muni_history_wiki, since):
        """Look for subsequent changes"""
        if pd.isna(gm_name):
            return None

        while True:
            gm_name = gm_name.replace(' (naamswijziging)', '')
            name_cleaned = gm_name.split('(')[0].strip().lower()
            mask = (
                (muni_history_wiki.name_cleaned == name_cleaned)
                & (muni_history_wiki['Opgegaan in'].notna())
            )
            if since:
                mask_since = (
                    (muni_history_wiki.until >= since)
                    | (muni_history_wiki.until.isna())
                )
                mask = mask & mask_since
            if sum(mask) != 1:
                break

            for nw_name in muni_history_wiki.loc[mask, 'Opgegaan in']:
                nw_name_cleaned = nw_name.split('(')[0].strip().lower()
            if nw_name_cleaned == name_cleaned: # e.g., Rozendaal
                break
            gm_name = nw_name
            for until in muni_history_wiki.loc[mask, 'until']:
                since = until
            if not until:
                break
        return gm_name


    def parse_muni_history_wiki(self, muni_history_wiki):
        """Create table linking former municipalities to subsequent one"""
        muni_history_wiki['province'] = muni_history_wiki.Provincie.map(
            lambda x: x.split('[')[0].replace('Friesland', 'Fryslân').strip().lower()
        )
        muni_history_wiki['name_cleaned'] = muni_history_wiki.Gemeente.map(
            lambda x: x.split('(')[0].strip().lower()
        )
        mask = muni_history_wiki['Alternatieve namen'].notna()
        variants = muni_history_wiki.loc[mask, 'Alternatieve namen'].map(
            lambda x: [variant.strip() for variant in x.lower().split(';')]
        )
        muni_history_wiki.loc[mask, 'variants'] = variants
        muni_history_wiki['since'] = muni_history_wiki['Bestaan vanaf'].apply(self.datestr_from_nl)
        muni_history_wiki['until'] = muni_history_wiki['Bestaan tot'].apply(self.datestr_from_nl)

        mask = (
            (muni_history_wiki.since <= self.match_year)
            | (muni_history_wiki.since.isna())
        )
        mask2 = ~muni_history_wiki['Opgegaan in'].str.contains(';').fillna(False)
        mask = mask & mask2
        muni_history_wiki = muni_history_wiki[mask].copy()

        latest_gm_name = [
            self.follow_wiki(name, muni_history_wiki, since)
            for name, since
            in zip(muni_history_wiki['Opgegaan in'], muni_history_wiki.until)
        ]
        muni_history_wiki['latest_gm_name'] = latest_gm_name

        return muni_history_wiki


    def parse_explanation(self, text):
        """Extract start date, end date and destination"""

        result_start = re.findall(CREATED, text)
        if result_start:
            d, m, Y = result_start[0]
            start = f'{Y}{m}{d}'
        else:
            start = None

        result_end = re.findall(ENDED, text)

        destination = None
        ratio = None
        if 'nieuwe naam' in text.lower():
            lines = text.split('\n')
            for line in lines:
                if not result_end:
                    result_end = re.findall(RENAMED, line)
                if line.lower().startswith('nieuwe naam'):
                    destination = re.findall(GM_CODE, line)[0]
                    ratio = 100
                    break

        if result_end:
            d, m, Y = result_end[0]
            end = f'{Y}{m}{d}'
            if self.match_year:
                if end[:4] >= self.match_year:
                    return start, end, None, None
        else:
            end = None

        if end and not 'nieuwe naam' in text.lower():
            lines = text.split('\n')
            destinations = pd.DataFrame()
            ignore = True
            for line in lines:
                if line.startswith('"'):
                    line = line[1:]
                if line.startswith('Opgeheven') & line.endswith('overgegaan naar:'):
                    ignore = False
                elif line == '' or line[0].isupper():
                    ignore = True
                if ignore:
                    continue
                if line.startswith('-'):
                    i = len(destinations)
                    destinations.loc[i, 'gm_code'] = re.findall(GM_CODE, line)[0]
                if line.startswith('...'):
                    try:
                        destinations.loc[i, 'population'] = re.findall(POP, line)[0]
                    except IndexError:
                        print(line)

            if not destinations.empty:
                if len(destinations) == 1:
                    destination = destinations.loc[0, 'gm_code']
                    ratio = 100
                else:
                    destinations['population'] = destinations.population.astype(int)
                    destinations = destinations.sort_values(
                        by='population', ascending=False
                    ).reset_index()
                    ratio = 100 * destinations.loc[0, 'population']
                    ratio /= destinations.population.sum()
                    if ratio > self.threshold_ratio:
                        destination = destinations.loc[0, 'gm_code']

        return start, end, destination, ratio


    def follow(self, gm_code, ratio, muni_history_cbs):
        """Look for subsequent changes"""
        nw_code = gm_code
        while nw_code:
            mask = muni_history_cbs.Gemeentecode == gm_code
            if sum(mask) == 0:
                break
            for text in muni_history_cbs.loc[mask, 'Toelichting']:
                _, _, nw_code, nw_ratio = self.parse_explanation(text)
                if nw_code:
                    ratio *= nw_ratio / 100
                    if ratio > self.threshold_ratio:
                        gm_code = nw_code
                    else:
                        nw_code = None
                        gm_code = None
        return gm_code, ratio


    def get_muni_history_cbs(self):
        """Get file with history of municipalities"""
        path = self.dir_config / 'Gemeente.xlsx'
        if path.is_file():
            return pd.read_excel(path, sheet_name='Gemeente')
        tmp_dir = Path('tmp_unzip_dir_will_be_removed')
        tmp_dir.mkdir()
        r = requests.get(MUNI_HISTORY_URL)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zip_obj:
            zip_obj.extractall(tmp_dir)
        path_muni_history_cbs = tmp_dir / 'Gemeente.xlsx'
        muni_history_cbs = pd.read_excel(
            path_muni_history_cbs,
            sheet_name='Gemeente'
        )
        if self.dir_config:
            new_path = self.dir_config / 'Gemeente.xlsx'
            shutil.move(path_muni_history_cbs, new_path)
        shutil.rmtree(tmp_dir)
        return muni_history_cbs


    def extract_province(self, name):
        """If present, extract province name"""
        gm_name = name
        prov = None
        if ')' in name:
            gm_name, prov = re.findall(NAME_PROV, name)[0]
        prov = PROV_ABBRS.get(prov, prov)
        return gm_name, prov


    def parse_muni_history_cbs(self):
        """Create table linking former municipalities to current one"""
        muni_history_cbs = self.get_muni_history_cbs()
        muni_history_cbs['name_cleaned'] = muni_history_cbs.Naam.str.replace(' (gemeente)', '', regex=False).str.lower()
        for col in muni_history_cbs.columns:
            try:
                muni_history_cbs[col] = muni_history_cbs[col].str.strip()
            except AttributeError:
                pass

        code_to_name = dict(
            zip(muni_history_cbs.Gemeentecode, muni_history_cbs.Naam)
        )
        code_to_name[None] = None
        since_dates, until_dates, destinations, ratios = zip(
            *muni_history_cbs.Toelichting.apply(self.parse_explanation)
        )
        muni_history_cbs['since'] = since_dates
        muni_history_cbs['until'] = until_dates
        mask = (
            (
                (muni_history_cbs.since <= self.match_year)
                | (muni_history_cbs.since.isna())
            ) & (
                (muni_history_cbs.until < self.match_year)
                | (muni_history_cbs.until.isna())
            )
        )
        muni_history_cbs = muni_history_cbs[mask].copy()

        current_gm_codes, ultimate_ratios = zip(*[
            self.follow(gm_code, ratio, muni_history_cbs)
            for i, (gm_code, ratio)
            in enumerate(zip(destinations, ratios))
            if mask[i]
        ])
        _, provs = zip(*[
            self.extract_province(name) for name in muni_history_cbs.Naam
        ])
        muni_history_cbs['province'] = provs
        muni_history_cbs['current_gm_code'] = current_gm_codes
        current_gm_names = muni_history_cbs.current_gm_code.map(code_to_name)
        muni_history_cbs['current_gm_name'] = current_gm_names
        muni_history_cbs['ratio'] = ultimate_ratios

        mask = muni_history_cbs.until.notna()
        return muni_history_cbs[mask]


    def get_config(self, dir_config):
        """Get config"""
        if dir_config:
            if isinstance(dir_config, str):
                dir_config = Path(dir_config)
            dir_config.mkdir(exist_ok=True)
            path_area_codes = dir_config / 'area_codes.csv'
            path_muni_history_wiki = dir_config / 'muni_history_wiki.csv'
        try:
            area_codes = pd.read_csv(path_area_codes, dtype='object')
        except (FileNotFoundError, UnboundLocalError):
            area_codes = self.get_area_codes()
            if dir_config:
                area_codes.to_csv(path_area_codes, index=False)
        for code, place in zip(area_codes.code, area_codes.place):
            self.replace[code] = place

        try:
            muni_history_wiki = pd.read_csv(path_muni_history_wiki)
        except (FileNotFoundError, UnboundLocalError):
            tables = pd.read_html(MUNI_HISTORY_WIKI_URL)
            for muni_history_wiki in tables:
                if muni_history_wiki.columns[0] == "A'damse code[1]":
                    break
            if dir_config:
                muni_history_wiki.to_csv(path_muni_history_wiki, index=False)
        self.muni_history_wiki = self.parse_muni_history_wiki(muni_history_wiki)

        wp_table = self.get_wp_table()
        for col in wp_table.columns:
            try:
                wp_table[col] = wp_table[col].str.strip()
            except AttributeError:
                pass
        gem_prov = {
            gem.lower(): prov
            for gem, prov
            in zip(wp_table.Naam_2, wp_table.Naam_4)
        }
        kwb_table = self.get_kwb_table()
        for col in kwb_table.columns:
            try:
                kwb_table[col] = kwb_table[col].str.strip()
            except AttributeError:
                pass

        mask_kwb = kwb_table.SoortRegio_2.isin(['Wijk', 'Buurt'])
        kwb_table = kwb_table[mask_kwb].copy()
        provinces = kwb_table.Gemeentenaam_1.str.lower().map(gem_prov)
        kwb_table['province'] = provinces

        wp = {}
        wp['any'] = {
            wp.lower(): gm
            for wp, gm in zip(wp_table.Woonplaatsen, wp_table.Naam_2)
            if list(wp_table.Woonplaatsen).count(wp) == 1
        }

        gm = {}
        gm['any'] = {gm.lower():gm for gm in set(wp_table.Naam_2)}
        for k, v in self.recode_gem.items():
            gm['any'][k] = v

        kwb = {}
        kwb['any'] = {
            wb.lower(): gm
            for wb, gm in zip(
                kwb_table.WijkenEnBuurten, kwb_table.Gemeentenaam_1
            )
            if list(kwb_table.WijkenEnBuurten).count(wb) == 1
        }

        for province in set(wp_table.Naam_4):
            subset = wp_table[wp_table.Naam_4 == province]
            key = province.lower()
            gm[key] = {gm.lower(): gm for gm in set(subset.Naam_2)}
            for k, v in self.recode_gem.items():
                gm[key][k] = v
            wp[key] = {
                wp.lower(): gm
                for wp, gm in zip(subset.Woonplaatsen, subset.Naam_2)
                if list(subset.Woonplaatsen).count(wp) == 1
            }
            subset = kwb_table[kwb_table.province == province]
            kwb[key] = {
                wb.lower(): gm
                for wb, gm in zip(subset.WijkenEnBuurten, subset.Gemeentenaam_1)
                if list(subset.WijkenEnBuurten).count(wb) == 1
            }

        return wp, gm, kwb, self.replace


    def clean(self, substring):
        """Strip and replace"""
        substring = substring.strip()
        if substring.startswith('bergen '):
            for string in ['n.h.', '(nh', ' nh', 'noord-holland']:
                if string in substring:
                    return 'Bergen (NH.)'
            for string in ['(l)', '(l.)', ' l ', 'limburg']:
                if string in substring:
                    return 'Bergen (L.)'
        if substring in self.ignore:
            return None
        if ' a/d ' in substring:
            substring = substring.replace(' a/d ', ' aan den ')
        if self.remove:
            for string in self.remove:
                substring = substring.replace(string, '')

        graven = re.findall(GRAVEN, substring)
        if graven:
            substring = f"'s-graven{graven[0]}"
        substring = re.sub(r"^'s ", "'s-", substring)
        if substring in self.replace:
            return self.replace[substring]
        return substring


    def filter_history(self, table, name, province, date, fuzzy, check_variants,
                       threshold_fuzzy):
        """Create relevant subset of table of former munis"""
        if isinstance(province, str):
            province = province.lower()
        if pd.notna(date) and isinstance(date, (float, int)):
            date = str(int(date))
        if date:
            mask = (
                (table.since.fillna('00000000') <= date) &
                (table.until.fillna('99999999') >= date)
            )
            subset = table[mask].copy()
        else:
            subset = table.copy()
        if province:
            mask = (subset.province == province) | (subset.province.isna())
            subset = subset[mask]
        if name.isnumeric() and "A'damse code[1]" in list(table.columns):
            mask = table["A'damse code[1]"] == int(name)
            subset = table[mask]
        elif check_variants:
            exploded = subset.explode('variants')
            mask = exploded.variants == name
            subset = exploded[mask]
        elif not fuzzy:
            mask = subset.name_cleaned == name
            subset = subset[mask]
        elif not subset.empty:
            match, score, _ = process.extractOne(
                name, subset.name_cleaned,
                scorer=fuzz.token_sort_ratio
            )
            if score >= threshold_fuzzy:
                mask = subset.name_cleaned == match
                subset = subset[mask]
        return subset


    def lookup_history(
        self,
        name,
        province,
        date,
        fuzzy,
        check_variants,
        threshold_fuzzy
    ):
        """Look for match in former municipalities"""
        gm_name = None
        subset = self.filter_history(
            self.muni_history_wiki, name, province, date, fuzzy,
            check_variants=False, threshold_fuzzy=threshold_fuzzy
        )
        if subset.empty and check_variants:
            subset = self.filter_history(
                self.muni_history_wiki, name, province, date, fuzzy,
                check_variants=True, threshold_fuzzy=threshold_fuzzy
            )
        if not subset.empty:
            subset = subset.drop_duplicates(subset='latest_gm_name')
        if len(subset) == 1:
            for date in subset.until:
                pass
            for gm_name in subset.latest_gm_name:
                name = gm_name.lower()
        subset2 = self.filter_history(
            self.muni_history_cbs, name, province, date, fuzzy,
            check_variants=False, threshold_fuzzy=threshold_fuzzy
        )
        if not subset2.empty:
            subset2 = subset2.drop_duplicates(subset='current_gm_name')
        if len(subset2) == 1:
            for gm_name in subset2.current_gm_name:
                pass
        return gm_name


    def guess(
        self,
        location_name,
        clean=True,
        check_history=True,
        check_variants=True,
        check_wp=True,
        check_wb=True,
        check_gm_fuzzy=True,
        check_fuzzy=True,
        check_history_fuzzy=True,
        check_wp_fuzzy=True,
        check_wb_fuzzy=True,
        province=None, date=None,
        delimiters=None,
        return_how=False,
        threshold_fuzzy=None
    ):
        """Guess corresponding municipality name
        :param location_name: user-provided location name
        :param clean: if True, value will be cleaned before attempting to find a
            match
        :param check_history: if True, it will be attempted to match the name
            with a former municipality and return the corresponding current
            municipality
        :param check_variants: if True, it will be attempted to match the name
            with a variant of a former municipality name, and return the
            corresponding current municipality
        :param check_wp: if True, it will be attempted to match the name
            with a place name and return the corresponding municipality
        :param check_wb: if True, it will be attempted to match the name
            with a neighbourhood name and return the corresponding municipality
        :param check_fuzzy: if False, all `check fuzzy` parameters will be set
            to False
        :param check_gm_fuzzy: if True, it will be attempted to find a fuzzy
            match with a municipality
        :param check_history_fuzzy: if True, it will be attempted to find a fuzzy
            match with a former municipality
        :param check_wp_fuzzy: if True, it will be attempted to find a fuzzy match
            with a place name
        :param check_wb_fuzzy: if True, it will be attempted to find a fuzzy match
            with a neighbourhood name
        :param province: only search for matches in this province
        :param date: limit search for matches among former municipalities to
            municipalities that existed at this date. Format as either %Y
            (e.g., '1950'), or %Y%m (e.g., '195001'), or %Y%m%d (e.g., '19500101')
        :param delimiters: characters to split input value by
        :param return_how: if True, the returned value will be a tuple containing
            the match found (if any), as well as the method the match was found
            with (e.g., 'wp' if the input value was matched with a place name,
            or 'gm_fuzzy' if a fuzzy match was found with a current municipality)
        :param threshold_fuzzy: override the value set when creating the
            GuessMunicipality object
        """
        if not check_history:
            check_history_fuzzy = False
        if not check_wp:
            check_wp_fuzzy = False
        if not check_wb:
            check_wb_fuzzy = False
        if not check_fuzzy:
            check_gm_fuzzy = False
            check_history_fuzzy = False
            check_wp_fuzzy = False
            check_wb_fuzzy = False
        if not threshold_fuzzy:
            threshold_fuzzy = self.threshold_fuzzy

        params_key = tuple(
            value for key, value
            in locals().items()
            if key not in ['return_how', 'self']
        )

        if params_key in self.found_results:
            result = self.found_results[params_key]
            if return_how:
                return result
            return result[0]

        # Deal with possibility that name may be Amsterdamse Code
        if isinstance(location_name, float):
            if location_name %1 == 0:
                location_name = int(location_name)
        if isinstance(location_name, int):
            location_name = str(location_name)

        if not isinstance(location_name, str):
            if return_how:
                return None, None
            return None
        location_name = location_name.lower()
        if province:
            province = province.strip()
            if province.lower() == 'friesland':
                province = 'Fryslân'
            key = province.lower()
            if key not in self.wp:
                key = 'any'
                province = None
        else:
            key = 'any'
        if delimiters:
            for dlm in self.delimiters:
                location_name = location_name.replace(dlm, ',')
            substrings = location_name.split(',')
        else:
            substrings = [location_name]
        if clean:
            substrings = [self.clean(sub) for sub in substrings]
        substrings = [sub for sub in substrings if len(sub) > 1]
        for substring in substrings:
            if substring in ['Bergen (NH.)', 'Bergen (L.)']:
                if return_how:
                    return substring, 'special'
                return substring
            if substring in self.gm[key]:
                result = self.gm[key][substring]
                self.found_results[params_key] = result, 'gm_prev'
                if return_how:
                    return result, 'gm'
                return result
        if check_history:
            for substring in substrings:
                result = self.lookup_history(
                    substring, province, date, fuzzy=False,
                    check_variants=check_variants,
                    threshold_fuzzy=threshold_fuzzy
                )
                if result:
                    self.found_results[params_key] = result, 'history_prev'
                    if return_how:
                        return result, 'history'
                    return result
        if check_wp:
            for substring in substrings:
                if substring in self.wp[key]:
                    result = self.wp[key][substring]
                    self.found_results[params_key] = result, 'wp_prev'
                    if return_how:
                        return result, 'wp'
                    return result
        if check_wb:
            for substring in substrings:
                if substring in self.wb[key]:
                    result = self.wb[key][substring]
                    self.found_results[params_key] = result, 'wb_prev'
                    if return_how:
                        return result, 'wb'
                    return result
        if check_gm_fuzzy:
            for substring in substrings:
                match, score = process.extractOne(substring, self.gm[key].keys(),
                                                  scorer=fuzz.token_sort_ratio)
                if score >= threshold_fuzzy:
                    result = self.gm[key][match]
                    self.found_results[params_key] = result, 'gm_fuzzy_prev'
                    if return_how:
                        return result, 'gm_fuzzy'
                    return result
        if check_history_fuzzy:
            for substring in substrings:
                result = self.lookup_history(
                    substring, province, date, fuzzy=True,
                    check_variants=check_variants,
                    threshold_fuzzy=threshold_fuzzy
                )
                if result:
                    self.found_results[params_key] = result, 'history_fuzzy_prev'
                    if return_how:
                        return result, 'history_fuzzy'
                    return result
        if check_wp_fuzzy:
            for substring in substrings:
                match, score = process.extractOne(substring, self.wp[key].keys(),
                                                  scorer=fuzz.token_sort_ratio)
                if score >= threshold_fuzzy:
                    result = self.wp[key][match]
                    self.found_results[params_key] = result, 'wp_fuzzy_prev'
                    if return_how:
                        return result, 'wp_fuzzy'
                    return result
        if check_wb_fuzzy:
            for substring in substrings:
                match, score = process.extractOne(substring, self.wb[key].keys(),
                                                  scorer=fuzz.token_sort_ratio)
                if score >= threshold_fuzzy:
                    result = self.wb[key][match]
                    self.found_results[params_key] = result, 'wb_fuzzy_prev'
                    if return_how:
                        return result, 'wb_fuzzy'
                    return result
        self.found_results[params_key] = None, 'no_match_found'
        if return_how:
            return None, 'no_match_found'
        return None
