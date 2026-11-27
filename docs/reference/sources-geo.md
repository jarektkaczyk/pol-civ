# Geography sources

## Conclusions

- Seven sources build the map of Poland: gmina outlines (GISCO LAU 2024), the 2026 unit register (GUS BDL), elevation (ETOPO 2022), land cover (ESA WorldCover 2021), forest type (Copernicus 2019), rivers (HydroRIVERS) and neighbours, lagoons and names (Natural Earth).
- Every source downloads without a login or key, through `Source.download()`. The two big rasters are read by HTTP range requests, so the cache holds about 60 MB, not several GB.
- The map has 7,708 hexes of 5 km (82 x 94); 4,805 are Polish land. Gmina codes are TERYT as of 2026 (2,479 gminy).

## Critical learnings

- The Polish LAU id is not the TERYT code. It is `10` + the GUS BDL unit id without its type digit (`1001121216101` = Kraków, TERYT6 `126101`). The type digit comes from the BDL register.
- BDL `units/search` filters by year, but stops at 2,000 records (page 20 of 100 answers HTTP 500). Gminy are fetched one kind at a time (urban 302, rural 1,453, urban-rural 724).
- The BDL firewall blocks bursts of requests for some minutes. The source waits 3 s between pages.
- Python's CA store on the build machine lacks the Certum Trusted Root CA that `bdl.stat.gov.pl` chains to. Fetch with `SSL_CERT_FILE` pointing at a bundle that adds it (the macOS system roots have it).
- WorldCover counts every patch with tree canopy as tree cover: 42% of Poland's land, against 29.6% official forest area (GUS). The `forest` shares follow WorldCover and the cover note says so.

## Sources

| id | Publisher | Dataset | Exact URL | Vintage | Licence | Level | Fields used | Caveats |
|---|---|---|---|---|---|---|---|---|
| `pl_geo_lau` | Eurostat GISCO | Local Administrative Units 2024, 1:1 million, TopoJSON, EPSG:4326 | https://gisco-services.ec.europa.eu/distribution/v2/lau/topojson/LAU_RG_01M_2024_4326.json | LAU 2024 (units of 1 January 2024; released 2025-06-30, file updated 2026-02-18 for Norway). Newest LAU year listed in `lau/datasets.json` on 2026-11-26. | (c) EuroGeographics for the boundaries; GISCO terms (reuse with attribution) | gmina | `GISCO_ID` (LAU id), `LAU_NAME`, `AREA_KM2`, outline | No `LAU_ID` field for Poland: the id is in `GISCO_ID`. 2,477 gminy; two 2026 gminy have no outline (below). |
| `pl_geo_teryt` | Statistics Poland (GUS) | BDL API unit register, `units/search?level={2,5,6}&year=2026&kind={1,2,3}` | https://bdl.stat.gov.pl/api/v1/units/search | Units in force in 2026 | GUS terms of use (reuse with attribution) | voivodeship, powiat, gmina | id (to TERYT), name, kind (gmina type) | 16 voivodeships, 380 powiaty, 2,479 gminy. Names cleaned: "Wałbrzych od 2013" to "Wałbrzych", "M.st.Warszawa od 2002" to "Warszawa". |
| `pl_geo_etopo` | NOAA NCEI, served by the NOAA PIFSC ERDDAP | ETOPO 2022 v1, 15 arc-second, ice surface (`ETOPO_2022_v1_15s`), ESRI ASCII in 7 latitude bands | https://oceanwatch.pifsc.noaa.gov/erddap/griddap/ETOPO_2022_v1_15s.esriAscii?z[33300:1:33539][3264:1:5904] (and the 6 other bands up to row 34836) | ETOPO 2022 (newest ETOPO release) | Public domain (U.S. Government work), doi:10.25921/fd45-gt74 | 15" grid (about 460 m x 290 m) | z (m) | Lon 13.6-24.6, lat 48.75-55.15. Rysy reads 2,466 m and Śnieżka 1,542 m at this resolution. |
| `pl_geo_worldcover` | ESA WorldCover consortium | ESA WorldCover 10 m 2021 v200, 15 COG tiles (N48-N54, E012-E024), 1:32 internal overview | https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51E018_Map.tif (and the other 14 tiles; byte ranges of the header and the 1125-pixel overview) | 2021 (v200, the newest WorldCover map) | CC BY 4.0, (c) ESA WorldCover project 2021 / Copernicus Sentinel data 2021 | 1/375 degree (about 300 m x 180 m) | class (10 tree ... 100 moss) | The overview holds valid class codes only (nearest or mode resampling). Sea is no data. |
| `pl_geo_forest_type` | Copernicus Global Land Service (VITO), on Zenodo | CGLS-LC100 collection 3, epoch 2019, Forest-Type layer (BigTIFF, 256 px deflate tiles) | https://zenodo.org/api/records/3939050/files/PROBAV_LC100_global_v3.0.1_2019-nrt_Forest-Type-layer_EPSG-4326.tif/content | 2019 (v3.0.1, the last epoch of the product) | CC BY 4.0, doi:10.5281/zenodo.3939050 | 100 m, kept every 4th pixel (1/252 degree) | forest type (needle, broad, mixed) | Read by range requests: 16 B header, 12.5 MB tag block, 26 tile rows. Used only to split tree cover into conifer, deciduous and mixed. |
| `pl_geo_hydrorivers` | WWF HydroSHEDS | HydroRIVERS v1.0, Europe, shapefile | https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_eu_shp.zip | v1.0 (2019 release of the 2013 network) | HydroSHEDS licence: free for scientific, educational and commercial use, with attribution (Lehner and Grill 2013) | river reach | `HYRIV_ID`, `NEXT_DOWN`, `UPLAND_SKM`, `DIS_AV_CMS`, `ORD_CLAS`, line | 5,816 reaches with 400 km2 or more upstream area in the window; chains drawn from 1,500 km2. No names: names come from Natural Earth. |
| `pl_geo_ne` | Natural Earth | 1:10m admin 0 countries, lakes, lakes Europe, rivers and lake centerlines, rivers Europe, release v5.1.2 | https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_10m_admin_0_countries.geojson (and the 4 other files) | v5.1.2 (pinned tag) | Public domain | country, lake, river | outlines, `name`, `name_pl`, `featurecla` | The 1:10m river file has English names only. Polish names come from the Europe file's `name_pl` (Oder to Odra) and one entry in code (Vistula to Wisła). Śniardwy and Mamry have no name in Natural Earth. |

## Detail

### Codes and gaps

- LAU 2024 vs the 2026 register: 2 new gminy (Szczawa `1207132`, Grabówka `2002162`, created after 1 January 2024) have no outline; their land is drawn as part of the gmina they were split from. 2 renamed rural gminy: Słupsk to Redzikowo (`2212082`), Nowe Miasto Lubawskie to Bratian (`2812052`). The interim `_world.notes` lists them.
- 17 of 2,479 gminy own no sample point (`_world.gminy_without_samples`, with the reason): 12 gminy smaller than the sample spacing (10 towns of 4 to 19 km2 such as Piastów, Sejny, Zambrów and Puck, rural Jejkowice at 8 km2, and Dziwnów on its narrow spit), 3 whose land lies in sea hexes and is drawn as a spit (Hel, Jastarnia, Krynica Morska), and the 2 new gminy. 288 gminy are the gmina of no hex (they share a hex with a larger neighbour).

### Rules applied in the world builder

- Land and water: 7 sample points per hex against the LAU and Natural Earth outlines; lagoons (Vistula, Curonian, Szczecin) are coastal water; a hex is a lake when WorldCover water is half its land points and ETOPO puts it above sea level.
- Relief, cover, rivers, lakes and spits: rules are in `world.json` `tables` and `docs/DATA_CONTRACTS.md` "world.json".

## Datasets looked for and not used

| Dataset | Reason |
|---|---|
| GUGiK PRG (state register of borders, gminy with current TERYT) | `opendata.geoportal.gov.pl` and the other geoportal hosts do not resolve from the build environment. |
| CORINE Land Cover 2018 | The Copernicus Land portal needs a login; the EEA image server (`image.discomap.eea.europa.eu`) refused the TLS connection. WorldCover 2021 is newer. |
| eTERYT TERC file | The download page is an ASP.NET form with no direct file link; the TERYT web service needs an account. The BDL unit register gives the same codes. |
| ETOPO on the NOAA CoastWatch ERDDAP (`coastwatch.pfeg.noaa.gov`, the usaciv host) | TLS connection refused from the build environment; the PIFSC ERDDAP serves the same dataset. |
| HydroLAKES | Global file only (820 MB). Lake outlines come from WorldCover water pixels instead. |
| Copernicus HRL Dominant Leaf Type, ESA CCI land cover | Login required (Copernicus Land portal, Climate Data Store). |
