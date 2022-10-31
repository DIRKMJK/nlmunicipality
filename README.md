Guess the Dutch municipality name from user-provided locations. 

# Simple example

```python
from nlmunicipality.guess import GuessMunicipality

guesser = GuessMunicipality('../data/config')
guesser.guess('Den Boscch')
guesser.guess('Sumar')
```

Note that creating a `guesser` object can take a minute.

See caveats below.

# How it works

Guessing the municipality may involve the following steps:

- Check if a result is already available for the input values provided (these are stored in the `found_results` attribute);
- Look for exact match in municipality names;
- Look for exact match in former municipality names (and variants) and return current municipality name;
- Look for unique exact match in place names and return corresponding municipality name;
- Look for unique exact match in neighbourhood names and return corresponding municipality name;
- Look for fuzzy match in municipality names;
- Look for fuzzy match in former municipality names (and variants) and return current municipality name;
- Look for unique fuzzy match in place names and return corresponding municipality name;
- Look for unique fuzzy match in neighbourhood names and return corresponding municipality name.

You can use the parameters for the `guess` method to control which steps will be included. For example, by setting `check_fuzzy=False`, you’ll exclude all steps involving looking for a fuzzy match.

## Match year

When creating a `GuessMunicipality` object, you can set the `match_year` parameter, which is the year for which a match will be tried to find. For example, with match_year set to 2020, Appingedam will be considered a municipality. If you set it to 2021 or higher, it will be considered a part of Eemsdelta.

## Custom recoding options

You can add options for recoding. For example, if the locations have been provided by foreign language speakers, they may use different spellings for some municipalities. Here’s an example of how you can deal with this:

```python
from nlmunicipality.guess import GuessMunicipality, RECODE_GEM

recode_gem = RECODE_GEM
recode_gem['haga'] = "'s-Gravenhage"
guesser = GuessMunicipality('../data/config', recode_gem=recode_gem)
guesser.guess('HAGA')
```

## Storing metadata

The package uses data from Statitics Netherlands (CBS) and from Wikipedia, which will be downloaded when you first create a `GuessMunicipality` object for a specific match year. If you set the `path_config` parameter when creating the guesser, this data will be stored so that it won’t be necessary to re-download each time you create a new guesser.

## Fuzzy matches

Unless you set `check_fuzzy=False`, an attempt will be made to find a fuzzy match when no exact match can be found. Using the `threshold_fuzzy` parameter, you can control how strict this will be applied (the parameter must have a value between 0 and 100, with 100 only allowing exact matches). Note that looking for fuzzy matches can take quite long. 

The `check_fuzzy` parameter can be set when creating the guesser, or when calling the `guess` method.

## Former municipality names

Unless you set `check_history=False` when calling the guess method, an attempt will be made to match the input value with a former municipality and return the municipality that it is now part of. An example of where this might be useful is when you want to analyse geographic patterns in voting over time.

Some former municipalities have been split up and divided over multiple municipalities. Using the `threshold_ratio` you can control how to deal with such situations. The default value is 80, which means that municipality A will be considered to be part of municipality B, if at least 80 percent of A’s population have been transferred to B.

Using the `date` parameter, you can limit the search to former municipalities that existed at that date. Provide the date as for example `1950` or `19500101`.

Note that it will also be attempted to interpret the input value as an [Amsterdamse Code][amco] and return the corresponding current municipality. For now, this only works with Amsterdamse Codes for *former* municipalities.


## Clean

If you set `clean=True` when calling the guess method, some cleaning will be applied to input values. For example, area codes will be replaced with the corresponding main place name (e.g., <code>020</code> with <code>amsterdam</code>. Country names will be ignored. 

Note that in a previous version, province names would be removed from the input value. This has been dropped, because handling province names is complicated: province names may also be (former) municipality names (Groningen, Utrecht, Zeeland) or be part of municipality names (Súdwest-Fryslân, Midden-Groningen). The best way to handle province names will depend on characteristics of the dataset you’re working with.

## Delimiters

When you call the guess method, you can set delimiters. Locations will then be split into substrings using the delimiters and for each substring, it will be tried to find a match. For example, if the place name is <code>Delfshaven, Rotterdam</code>, it will be tried to find a match first for <code>delfshaven</code> and then for <code>rotterdam</code>.

## Province

If you know that the location is within a specific province, you can specify this, which may prevent false matches. You could opt to combine this with setting a lower threshold for the quality of matches.

```python
from nlmunicipality.guess import GuessMunicipality

guesser = GuessMunicipality('../data/config', threshold=80)
guesser.guess('Valkenburg', province='Zuid-Holland')
```

## Other options

See `help(GuessMunicipality.guess)`.

## Check what works

What options get the best results will depend on characteristics of the dataset. You may want to try multiple options and compare where the results differ, to get an idea which approach best fits the data you’re working with.

For example:
```python
guesser = GuessMunicipality('../data/config')

df['guess_exact'] = [
    guesser.guess(name, check_fuzzy=False) for name in df.place_name
]
df['guess_fuzzy'] = df.place_name.apply(guesser.guess)
mask = df.guess_exact != df.guess_fuzzy

df[mask].sample(5)
```

You can set the `return_how` parameter to get a hint as to how a match was found.

# Caveats

nlmunicipality may return incorrect matches or fail to return correct matches.


# Installation

`pip install nlmunicipality`

# Todo

Convert coordinates to municipality.

[stack]:https://stackoverflow.com/questions/15268953/how-to-install-python-package-from-github
[amco]:https://nl.wikipedia.org/wiki/Amsterdamse_code

