# placekey_poc
proof of concept for placekey api

# Placekey 
placekey is like a universal foreign key for geospatial data.  it's a unique open standard identifier for addresses and points of interest

# Mapbox
This project uses Mapbox to parse addresses into its components then passes into placekey.  The idea is to clean up the address passed in.  

# Considerations
To run the code you'll need an API key for both mapbox and placekey.  

# How to run
python main.py <csv_input> <output_csv> <Address_column_name> <Name_column_name>
