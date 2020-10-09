# -*- coding: utf-8 -*-
#
# Created by Alex Molina
# september 2020
# 


import geopandas
import pandas as pd
import contextily as ctx
import matplotlib.pyplot as plt
import simplejson as json
import requests
from nltk.util import everygrams
from geopandas import GeoDataFrame
from opencage.geocoder import OpenCageGeocode
from anytree import NodeMixin, RenderTree, search, PreOrderIter
from anytree.dotexport import RenderTreeGraph
from shapely.geometry import box, Point



class GeospatialTree(NodeMixin):
    """Geospatial Tree class"""
    def __init__(self, name, geometry=None, length=0, width=0, parent=None, children=None):
        super(GeospatialTree, self).__init__()
        self.name = name
        self.length = length
        self.width = width
        self.parent = parent
        self.geometry = geometry
        if children:
            self.children = children

    def __repr__(self):
        return '• {} {}'.format(self.name, self.geometry)

    def load_findings(self, data_path, n_rows=47):
        df = pd.read_excel(data_path, nrows=n_rows, na_filter=True)
        df.drop(df.columns[3:8], axis=1, inplace=True)
        df.columns = ['region', 'finding', 'city']
        self.findings_df = df

    def geoparse_findings(self):
        for _, region, finding, city in self.findings_df.itertuples():
            print('\n* finding description>{}\nregion>{}'.format(finding, region))
            node = search.find(self, lambda node: node.name == region)
            if node:
                for child in node.children:
                    bounds_str =self.bound_string(child)
                    queries = [(q, bounds_str) for q in self.queries_generator(child, finding)]
                    # print('queries>{}\n'.format(queries))
                    for (query, bounds) in queries:
                        print('\nq>{}\nbound name>{}\nbound coords>{}'.format(query, child.name, bounds))
                        response = self.call_opencage(query, bounds)
                        str_response = json.dumps(response, ensure_ascii=False, encoding='utf-8', indent=2)
                        print('{}\n{}'.format(query, str_response))
                        if len(response) > 0:
                            for r in response:
                                try:
                                    x1=r['bounds']['southwest']['lng']
                                    y1=r['bounds']['southwest']['lat']
                                    x2=r['bounds']['northeast']['lng']
                                    y2=r['bounds']['northeast']['lat']
                                    geometry_r = box(x1, y1, x2, y2)
                                except Exception as e:
                                    x1=r['geometry']['lng']
                                    y1=r['geometry']['lat']
                                    geometry_r = Point()

                                if child.geometry.contains(geometry_r):
                                    print('---- FOUND {} ----'.format(query))
                                    print('insert>{} as child of {}'.format(r['formatted'], child.name))
                                    GeospatialTree(name=r['formatted'], geometry=geometry_r, parent=child)

    def queries_generator(self, node, finding):
        prepro_finding = self.preprocess(finding)
        # for ngram in self.ngrams(finding):
        #     q = '{}'.format(ngram, child_name)
        #     bounds_str =self.bound_string(child)
        #     yield(q, bounds_str)
        #response = self.call_geoparseMX(prepro_finding)
        #json_response = json.loads(response)
        #print('labeled>',json_response['labeled'])
        q = '{}'.format(prepro_finding)
        yield q

    def preprocess(self, text):
        text = text.lower()
        text = text.replace('"', '')
        text = text.replace('(', '')
        text = text.replace(')', '')
        return text

    def ngrams(self, text):
        text_l = text.lower()
        tokens = text_l.split()
        for toks in list(everygrams(tokens)):
            yield ' '.join(toks)

    def bound_string(self, node):
        # see https://shapely.readthedocs.io/en/latest/manual.html?highlight=rectangular%20polygon%20from%20the%20provided%20bounding%20box#polygons
        polygon = list(node.geometry.exterior.coords)
        bounds_str = '{},{},{},{}'.format(polygon[3][0],polygon[3][1],polygon[1][0],polygon[1][1])
        return bounds_str

    def call_geoparseMX(self, text):
        geoparser_url = "http://geoparsing.geoint.mx/ws/"
        data = dict({"text" : text})
        response = requests.post(geoparser_url, json = data, headers={"Content-Type":"application/json"})
        json_geoparsed = json.dumps(response.json(), encoding="utf8", indent=2, ensure_ascii=False)
        return json_geoparsed

    def call_opencage(self, query_text, bounds_str):
        with open('key', 'r') as f:
            key = f.read()
        geocoder = OpenCageGeocode(key)
        try:
            results = geocoder.geocode(query_text,
                bounds=bounds_str,
                pretty=1,
                language='es',
                roadinfo=1,
                country_code='MX')
        except Exception as e:
            raise e
        return results


# UTILITIES

def build_geotree(df):
    # by convention id=0 will be the root
    root = df.iloc[0]
    geotree = GeospatialTree(name=root['name'], geometry=root['geometry'])
    df = df.iloc[1:]
    df_region = df[df['parent'] == 0]
    for index, parent_id, name, geometry in df_region.itertuples():
        #print('insert', index, parent_id, name)
        subtree = GeospatialTree(name=name, geometry=geometry, parent=geotree)
        for (i,p,n,g) in (df[df['parent'] == index]).itertuples():
            #print('insert', i, p, n)
            GeospatialTree(name=n, geometry=g, parent=subtree)

    return geotree

def build_geodf(df_uri):
    """read initial data and build geographic data frame"""
    # Expected format is:
    # id  parent  name    minlon  minlat  maxlon  maxlat
    # 0   0   Coahuila    -103.9600019    24.54268406 -99.8431198 29.88002429
    # 1   0   Laguna 1    -103.5109366    24.73977397 -102.4467635    25.77617708
    # 2   0   Laguna 2    -103.4159638    24.75439672 -101.3792519    26.75409914
    df = pd.read_csv(df_uri, sep='\t', index_col=0)
    geometry = [box(x1, y1, x2, y2) for x1,y1,x2,y2 in zip(df.minlon, df.minlat, df.maxlon, df.maxlat)]
    df = df.drop(['minlon', 'minlat', 'maxlon', 'maxlat'], axis=1)
    geodf = GeoDataFrame(df, crs="EPSG:4326", geometry=geometry)
    return geodf

def tree_as_df(tree):
    t = []
    for node in PreOrderIter(tree):
        try:
            parent = node.parent.name
        except Exception as e:
            parent='root'
        name=node.name
        geo=node.geometry
        t.append((parent, name, geo))
    df = pd.DataFrame(t)
    df.columns = ['parent', 'name', 'geometry']
    geodf = GeoDataFrame(df, crs="EPSG:4326", geometry='geometry')
    return geodf

def mapplot(geodf):
    # Convert the data to Web Mercator
    # Web map tiles are typically provided in Web Mercator (EPSG 3857), so we need to make sure to convert our data first to the same CRS to combine our polygons and background tiles in the same map:
    try:
        CRS_df = geodf.to_crs(epsg=3857)
    except Exception as e:
        raise e

    # # we are using an extent around Mexico for the examples
    # #extent = (-12600000, -10300000, 1800000, 3800000)
    extent =    (-12000000, -10600000, 2750000, 3750000)
    ax = CRS_df.plot(figsize=(8, 8), alpha=0.3, edgecolor='k')
    CRS_df.apply(lambda x: ax.annotate(text=x.name, xy=x.geometry.centroid.coords[0], ha='center'), axis=1);
    ax.axis(extent)
    ctx.add_basemap(ax, source=ctx.providers.Stamen.TonerLite)
    #plt.show()
    plt.savefig('outputs/maptile.png')


if __name__ == '__main__':

    REGIONS_URI = './data/bounds_coahuila.tsv'
    FOSAS_URI = './data/OperativosdeCampo2017-2020.xlsx'

    geodf = build_geodf(REGIONS_URI)

    ### creating a geographic tree from geo-data frame
    geotree = build_geotree(geodf)

    ### initial tree
    RenderTreeGraph(geotree).to_picture("outputs/inittree.png")

    ### loading findings data
    geotree.load_findings(FOSAS_URI)

    ### query geoparser ws with findings data
    geotree.geoparse_findings()

    ### final tree
    RenderTreeGraph(geotree).to_picture("outputs/finaltree.png")

    ### save new data
    tree_df = tree_as_df(geotree)
    tree_df.to_file('outputs/spatial_data.json', driver="GeoJSON")

    ### save map
    mapplot(tree_df)

