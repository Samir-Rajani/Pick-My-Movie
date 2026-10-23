# Data attribution and license

The movie catalog and ratings source used by this project is [Movie Recommendation System by Manas Parashar on Kaggle](https://www.kaggle.com/datasets/parasharmanas/movie-recommendation-system). The Kaggle data card identifies the database license as [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1.0/) and the contents as belonging to their original authors.

`movies.csv` is redistributed from that dataset. `model.json` is generated from its `ratings.csv` by `build_model.py`; it is a derived data artifact. These files are provided under the source database's applicable attribution and share alike terms. The large `ratings.csv` remains excluded from Git and deployment; obtain it from the source link to reproduce the model.

This notice applies to the data files, not to the app's original code or interface.
