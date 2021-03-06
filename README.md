# OnMapLoader
The QGIS Plugin for loading Korea NGII OnMap(PDF Map)

국토리지정보원 온맵(On-Map) 로딩 플러그인

국토리지정보원의 온맵(On-Map) 지도를 GeoPackage로 만든 후 QGIS에 올바른 지리좌표에 맞게 불러주는 플러그인입니다.
온맵에 포함된 모든 지도 레이어들과 영상을 지리정보로 만들어 주어 다른 지리정보와 함께 사용할 수 있게 해줍니다.

## 왜 GIS 툴에서 온맵을 사용하려 하는가?
  - 온맵은 PDF 이기에 쉽게 출력물로 만들 수 있는 좋은 지도입니다.
  - 온맵 플레이어를 이용하면 다양한 사용자 지도를 만들 수 있습니다.
  - 하지만, 일반적인 공간정보와 중첩하기에는 PDF 라는 출력용 포맷에서 오는 제약이 많습니다.
  - 이미 고수들은 Global Mapper 등의 프로그램을 이용해 온맵을 다양하게 변환해 사용중이지만 정말 고수만 할 수 있지요~
  - 이제 누구나 쉽게 온맵에 다양한 공간정보를 올려봅시다!!

## OnMap Loader란?
  - 무료로 사용할 수 있는 GIS 툴인 QGIS의 플러그인입니다.
  - 공간정보 지식이 없어도 누구나 쉽게 사용할 수 있습니다.
  - 온맵 PDF에서 지도와 영상을 자동 추출해 GIS에 올려줍니다.
  - 온맵의 도엽명에서 해당 지도의 위치와 좌표계를 판단해 지리적으로 정확한 위치를 갖도록 해줍니다.
  - 사용자가 선택한 레이어만 공간정보로 변환할 수 있어 효율적입니다.
  - 변환된 온맵의 공간정보에 다양한 다른 공간정보를 올리 수 있습니다.

## OnMap Loader 설치
  1. 무료 공간정보 툴인 QGIS를 설치합니다.
   - http://qgis.org/ko/site/forusers/download.html 에서 설치파일 받아
   - 실행만 하면 누구나 쉽게 설치할 수 있습니다.
  2. ~~OnMap Loader를 설치합니다.~~
   - ~~설치된 QGIS Desktop을 실행합니다.~~
   - ~~플러그인 – 플러그인 관리 및 설치… 메뉴 선택해 플러그인 관리자를 띄웁니다.~~
   - ~~검색: 항목에 OnMap을 입력해 OnMap Loader를 찾습니다.~~
      ![Plugin Manager](images/install_pluginmamager.png)
   - ~~[플러그인 설치] 버튼을 눌러 설치하면 끝~~
   
  2. (임시안내) OnMap Loader를 설치합니다.
   - 설치된 QGIS Desktop을 실행합니다.
   - 아직 QGIS Plugin Repository 에서 승인이 안나서 임시적인 방법을 안내합니다.
   - 다음 경로에서 플러그인 압축파일을 다운로드 합니다. https://github.com/Gaia3D/OnMapLoader/raw/master/release/OnMapLoader_1.3.zip
   - 사용자 폴더에 있는 .qgis2 폴더 아래의 python/plugins 폴더 아래에 압축파일을 풀어 줍니다.
   - 이 때 OnMapLoader 폴더가 이중으로 생기면 안됩니다. 즉 OnMapLoader 폴더 안에 또 OnMapLoader 폴더가 생기면 안됩니다.
   - 플러그인 – 플러그인 관리 및 설치… 메뉴 선택해 플러그인 관리자를 띄웁니다.
   - 플러그인 관리자의 설치됨 탭에서 OnMapLoader를 찾아 체크하여 활성화 해 줍니다.

## 처음으로 OnMap Loader 실행하기
  1. 툴바에서 ON MAP 아이콘을 찾아 누릅니다.

   ![OnMap Icon](images/toolbar_icon.png)

  2. 창이 뜨면 [선택…] 버튼을 누릅니다.

   ![ClickBrowse](images/dialog_browsebutton.png)

  3. 온맵 PDF 파일을 선택합니다.

   ![Browse PDF](images/dialog_browsepdf.png)

  4. 공간정보로 변환할 레이어를 선택합니다.

   ![Select Layer](images/dialog_layer.png)

  5. [온맵 변환 시작] 버튼을 누릅니다.

  끝입니다. 정말 이게 사용법의 다입니다.
    
## 실제로 온맵을 QGIS로 가져와 보자
  1. 국토지리정보원 공간정보플랫폼에서 원하는 지역의 온맵을 다운로드 받습니다.
  2. OnMap Loader에서 다운받은 온맵 PDF를 선택합니다.
  3. 온맵에 들어있는 영상을 포함한 다양한 레이어들이 보입니다.
  4. [온맵 변환 시작] 버튼을 누르고 진행상황을 지켜봅니다.

   ![Progressing](images/dialog_progress.png)

  공간정보로 변환된 온맵이 QGIS에 올라왔습니다.

   ![Completed](images/qgis_complete.png)

## 다른 공간정보와 함께 온맵을 보자
  * 다음 지도 위에 온맵 공간정보가 올라온 모습
  ![다음 지도 위에 온맵 공간정보가 올라온 모습](images/with_daummap.png)

  * 구글 지도 위에 건물과 등고선만 강조한 모습
  ![구글 지도 위에 건물과 등고선만 강조한 모습](images/with_googlemap.png)

## 더 빨리 온맵 공간정보를 불러오자
  - 온맵을 OnMap Loader를 이용해 공간정보를 불러오는 데 짧으면 수분, 길면 십여분 정도의 시간이 걸립니다.
  - 이 시간의 대부분이 PDF 파일에서 공간정보를 추출해 올바른 위치로 변환하는 시간입니다.
  - 그럼 변환된 공간정보를 저장해 두면 더 빠르지 않을까요?
  - OnMap Loader는 변환시 공간정보를 지오패키지(GPKG)로 저장해 이후 1분 내에 불러올 수 있게 해줍니다.

  ![Using Geopackage](images/use_geopackage.png)

    - 지오패키지(GeoPackage)는 SHP를 대체하는 OGC의 새로운 공간정보 교환 표준입니다.
    - 지오패키지에는 한 파일에 벡터와 영상이 모두 들어갈 수 있고, 좌표계 등의 메타정보도 들어갑니다.

## 내부적으로 수행되는 작업들
  OnMap Loader는 내부적으로 전문적인 지식이 필요한 공간정보 작업을 수행합니다.
  
  - PDF에서 레이어 정보를 추출합니다.
  - GDAL/OGR로 PDF에서 지도를 벡터로 추출합니다.
  - PDF에서 조각으로 잘린 영상을 추출해 한 장으로 결합합니다.
  - 도엽명에서 해당 온맵의 공간적 위치와 좌표계를 판단해 지리적 위치에 맞게 Affine 변환합니다.
  - 추출된 공간정보를 모두 한 개의 지오패키지 파일에 저장합니다.
  - 지오패키지에 저장된 공간정보를 QGIS에 불러옵니다.
  
