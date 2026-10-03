import os
import requests
import networkx as nx
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import QLabel
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.utils import platform

# Tentativa de importar a biblioteca para ler GeoPackage sem QGIS
try:
    import fiona
    from shapely.geometry import shape
    FIONA_DISPONIVEL = True
except ImportError:
    FIONA_DISPONIVEL = False

class RotasMSAppLayout(BoxLayout):
    def __init__(self, **kwargs):
        super(RotasMSAppLayout, self).__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 20
        self.spacing = 15

        # Título
        self.add_widget(QLabel(
            text='Rotas MS - Mobile', 
            font_size=22, 
            size_hint_y=None, 
            height=40,
            color=(0.1, 0.4, 0.8, 1)
        ))

        # Origem
        self.add_widget(QLabel(text='Ponto de Origem (Lat, Lon):', size_hint_y=None, height=25))
        self.input_origem = TextInput(
            text='-20.4697, -54.6163', 
            multiline=False, 
            size_hint_y=None, 
            height=40
        )
        self.add_widget(self.input_origem)

        # Destino
        self.add_widget(QLabel(text='Ponto de Destino (Lat, Lon):', size_hint_y=None, height=25))
        self.input_destino = TextInput(
            text='-20.5000, -54.5500', 
            multiline=False, 
            size_hint_y=None, 
            height=40
        )
        self.add_widget(self.input_destino)

        # Opção Offline
        layout_chk = BoxLayout(orientation='horizontal', size_hint_y=None, height=40)
        self.chk_offline = CheckBox(size_hint_x=None, width=40)
        layout_chk.add_widget(self.chk_offline)
        layout_chk.add_widget(QLabel(text='Forçar Modo Offline (usar rotas_plugin.gpkg)'))
        self.add_widget(layout_chk)

        # Botão Gerar Rota
        self.btn_gerar = Button(
            text='🗺️ Gerar Rota e Salvar KML', 
            background_color=(0.1, 0.6, 0.3, 1),
            size_hint_y=None, 
            height=50
        )
        self.btn_gerar.bind(on_press=self.executar_geracao_rota)
        self.add_widget(self.btn_gerar)

        # Status / Log
        self.lbl_status = QLabel(
            text='Aguardando coordenadas...', 
            font_size=14,
            text_size=(350, None)
        )
        self.add_widget(self.lbl_status)

    def parse_coordenada(self, texto):
        try:
            partes = [p.strip() for p in texto.split(",")]
            lat, lon = float(partes[0]), float(partes[1])
            return (lon, lat)  # OSRM/GeoJSON usa (lon, lat)
        except Exception:
            return None

    def _obter_rota_osrm(self, p1, p2):
        url = f"http://router.project-osrm.org/route/v1/driving/{p1[0]},{p1[1]};{p2[0]},{p2[1]}?overview=full&geometries=geojson"
        try:
            r = requests.get(url, timeout=6)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == "Ok":
                    coords = data["routes"][0]["geometry"]["coordinates"]
                    dist = data["routes"][0]["distance"] / 1000.0
                    return coords, dist
        except Exception:
            pass
        return None, 0.0

    def _baixar_gpkg_se_necessario(self, caminho_gpkg):
        """Baixa o arquivo do Google Drive automaticamente caso não exista no celular"""
        if os.path.exists(caminho_gpkg):
            return True

        self.lbl_status.text = "Baixando base offline (63 MB). Aguarde..."
        
        # ID extraído do link do seu Google Drive compartilhado
        file_id = "125h-7gH5tcFSELeCFmau0briqghkHCUI"
        url = f"https://drive.google.com/uc?export=download&id={file_id}"

        try:
            session = requests.Session()
            response = session.get(url, stream=True, timeout=30)
            
            # Lidar com confirmação de arquivo grande do Google Drive
            for key, value in response.cookies.items():
                if key.startswith('download_warning'):
                    url = f"{url}&confirm={value}"
                    response = session.get(url, stream=True, timeout=30)
                    break

            with open(caminho_gpkg, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception as e:
            self.lbl_status.text = f"Erro ao baixar base offline: {str(e)}"
            return False

    def _obter_rota_offline_gpkg(self, p_origem, p_destino):
        if not FIONA_DISPONIVEL:
            raise Exception("Biblioteca Fiona/Shapely não instalada no pacote Android.")
            
        # Define o diretório de dados do app no celular ou pasta atual
        if platform == 'android':
            from android.storage import app_storage_path
            dir_path = app_storage_path()
        else:
            dir_path = os.getcwd()

        caminho_gpkg = os.path.join(dir_path, "rotas_plugin.gpkg")

        # Garante o download do arquivo do Drive se ainda não estiver baixado
        if not self._baixar_gpkg_se_necessario(caminho_gpkg):
            raise Exception("Não foi possível obter o arquivo rotas_plugin.gpkg.")

        G = nx.Graph()
        with fiona.open(caminho_gpkg) as src:
            for feat in src:
                geom_dict = feat['geometry']
                if not geom_dict:
                    continue
                geom = shape(geom_dict)
                linhas = geom.geoms if geom.geom_type == 'MultiLineString' else [geom]
                for linha in linhas:
                    pts = list(linha.coords)
                    for i in range(len(pts) - 1):
                        pt1 = (round(pts[i][0], 5), round(pts[i][1], 5))
                        pt2 = (round(pts[i+1][0], 5), round(pts[i+1][1], 5))
                        dist = ((pt1[0]-pt2[0])**2 + (pt1[1]-pt2[1])**2)**0.5
                        G.add_edge(pt1, pt2, weight=dist)

        todos_nos = list(G.nodes)
        if not todos_nos:
            raise Exception("Rede de estradas vazia no GeoPackage.")

        def no_mais_proximo(p):
            return min(todos_nos, key=lambda n: (n[0] - p[0])**2 + (n[1] - p[1])**2)

        no_a = no_mais_proximo(p_origem)
        no_b = no_mais_proximo(p_destino)

        try:
            caminho_nos = nx.shortest_path(G, source=no_a, target=no_b, weight='weight')
            distancia_total = len(caminho_nos) * 1.5
            return caminho_nos, distancia_total
        except nx.NetworkXNoPath:
            raise Exception("Nenhum caminho encontrado entre os pontos na rede offline.")

    def executar_geracao_rota(self, instance):
        pt_origem = self.parse_coordenada(self.input_origem.text)
        pt_destino = self.parse_coordenada(self.input_destino.text)

        if not pt_origem or not pt_destino:
            self.lbl_status.text = "Erro: Coordenadas inválidas. Use o formato: Lat, Lon"
            return

        usar_offline = self.chk_offline.isChecked()
        coords_rota = []
        distancia = 0.0

        try:
            if not usar_offline:
                self.lbl_status.text = "Consultando OSRM (Online)..."
                coords_rota, distancia = self._obter_rota_osrm(pt_origem, pt_destino)
                if not coords_rota:
                    self.lbl_status.text = "Falha online. Tentando modo offline..."
                    usar_offline = True

            if usar_offline:
                self.lbl_status.text = "Preparando modo offline..."
                coords_rota, distancia = self._obter_rota_offline_gpkg(pt_origem, pt_destino)

            if not coords_rota:
                self.lbl_status.text = "Erro: Não foi possível gerar a rota."
                return

            if platform == 'android':
                from android.storage import primary_external_storage_path
                dir_path = primary_external_storage_path()
            else:
                dir_path = os.getcwd()

            caminho_kml = os.path.join(dir_path, 'rota_gerada_mobile.kml')
            
            kml_conteudo = '<?xml version="1.0" encoding="UTF-8"?>\n'
            kml_conteudo += '<kml xmlns="http://www.opengis.net/kml/2.2">\n  <Document>\n'
            kml_conteudo += '    <name>Rota Calculada RotasMS</name>\n'
            kml_conteudo += '    <Placemark>\n      <name>Caminho da Rota</name>\n      <LineString>\n        <coordinates>\n'
            
            for pt in coords_rota:
                kml_conteudo += f'          {pt[0]},{pt[1]},0\n'
                
            kml_conteudo += '        </coordinates>\n      </LineString>\n    </Placemark>\n'
            kml_conteudo += '  </Document>\n</kml>'

            with open(caminho_kml, 'w', encoding='utf-8') as f:
                f.write(kml_conteudo)

            modo = "Offline (Google Drive/GPKG)" if usar_offline else "Online"
            self.lbl_status.text = f"Sucesso! ({modo}) ~{distancia:.2f} km\nSalvo em: {caminho_kml}"

        except Exception as e:
            self.lbl_status.text = f"Erro no processo: {str(e)}"

class RotasMSApp(App):
    def build(self):
        return RotasMSAppLayout()

if __name__ == '__main__':
    RotasMSApp().run()