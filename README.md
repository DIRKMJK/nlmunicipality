Guess the Dutch municipality name from user-provided locations. This involves the following steps:

- Look for exact match in municipality names;
- Look for unique exact match in place names (from Statistics Netherlands) and return corresponding municipality name;
- Look for fuzzy match in municipality names;
- Look for unique fuzzy match in place names and return corresponding municipality name.

During preprocessing, area codes are replaced with the corresponding main place name (e.g., <code>020</code> with <code>amsterdam</code>. Country and province names are ignored (except for province names that are also municipality names).
Locations are split into substrings using a number of delimiters and for each substring, it will be tried to find a match. For example, if the place name is <code>Delfshaven, Rotterdam</code>, it will be tried to find a match first for <code>delfshaven</code> and then for <code>rotterdam</code>.
Finding fuzzy matches takes a bit of time. With large datasets, it may be advisable to use multiprocessing. If the dataset contains duplicate locations, keep in mind to apply the guesser only to a set of the locations to create a dictionary; you can then use that dictionary to recode all locations.  

# Caveats

nlmunicipality may return incorrect matches or fail to return correct matches.
If multiple locations are provided, the function will return the first match that is found.
If the location contains the province name Utrecht or Groningen, the function will return the city of that name (unless another match is found first, e.g. <code>De Bilt</code> for <code>De Bilt, Utrecht</code>)

# Example

```python
from nlmunicipality.guess import GuessMunicipality

guesser = GuessMunicipality('../data/config')
guesser.guess('Den Boscch')
guesser.guess('Sumar')
```

Depending on the specifics of the dataset you are dealing with, you can adjust the parameters. For example, if the locations have been provided by foreign language speakers, they may use different spellings for some municipalities. Here’s an example of how you can deal with this:

```python
from nlmunicipality.guess import GuessMunicipality, RECODE_GEM

recode_gem = RECODE_GEM
recode_gem['haga'] = "'s-Gravenhage"
guesser = GuessMunicipality('../data/config', recode_gem=recode_gem)
guesser.guess('HAGA')
```

If you know that the location is within a specific province, you can specify this, which may prevent false matches. You could opt to combine this with setting a lower threshold for the quality of matches.

```python
from nlmunicipality.guess import GuessMunicipality

guesser = GuessMunicipality('../data/config', threshold=80)
guesser.guess('Valkenburg', province='Zuid-Holland')
```


# Installation

See discussion [here][stack].

# Todo

Convert coordinates to municipality.

[stack]:https://stackoverflow.com/questions/15268953/how-to-install-python-package-from-github

