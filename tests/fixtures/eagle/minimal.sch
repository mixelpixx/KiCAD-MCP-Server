<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE eagle SYSTEM "eagle.dtd">
<eagle version="9.6.2">
  <drawing>
    <settings>
      <setting alwaysvectorfont="no"/>
    </settings>
    <grid distance="0.1" unitdist="inch" unit="inch" multiple="1" display="yes" altdistance="0.01" altunitdist="inch" altunit="inch"/>
    <layers>
      <layer number="91" name="Nets" color="2" fill="1" visible="yes" active="yes"/>
      <layer number="94" name="Symbols" color="4" fill="1" visible="yes" active="yes"/>
    </layers>
    <schematic>
      <libraries>
        <library name="default">
          <symbols>
            <symbol name="R">
              <wire x1="-1.016" y1="0.254" x2="1.016" y2="0.254" width="0.1524" layer="94"/>
              <wire x1="1.016" y1="0.254" x2="1.016" y2="-0.254" width="0.1524" layer="94"/>
              <wire x1="1.016" y1="-0.254" x2="-1.016" y2="-0.254" width="0.1524" layer="94"/>
              <wire x1="-1.016" y1="-0.254" x2="-1.016" y2="0.254" width="0.1524" layer="94"/>
              <pin name="1" x="-1.016" y="0" length="point" direction="pas" rot="R180"/>
              <pin name="2" x="1.016" y="0" length="point" direction="pas"/>
            </symbol>
          </symbols>
          <devicesets>
            <deviceset name="R" prefix="R">
              <gates>
                <gate name="G$1" symbol="R" x="0" y="0"/>
              </gates>
              <devices>
                <device name="">
                  <connects>
                    <connect gate="G$1" pin="1" pad="1"/>
                    <connect gate="G$1" pin="2" pad="2"/>
                  </connects>
                </device>
              </devices>
            </deviceset>
          </devicesets>
        </library>
      </libraries>
      <parts>
        <part name="R1" library="default" deviceset="R" device="" value="10k"/>
      </parts>
      <sheets>
        <sheet>
          <instances>
            <instance part="R1" gate="G$1" x="50.8" y="50.8" rot="R0"/>
          </instances>
          <busses>
          </busses>
          <nets>
            <net name="N$1" class="0">
              <segment>
                <pinref part="R1" gate="G$1" pin="1"/>
                <wire x1="49.784" y1="50.8" x2="45.72" y2="50.8" width="0.1524" layer="91"/>
                <label x="45.72" y="50.8" size="1.778" layer="95" rot="R0">NET1</label>
              </segment>
            </net>
            <net name="GND" class="0">
              <segment>
                <pinref part="R1" gate="G$1" pin="2"/>
                <wire x1="51.816" y1="50.8" x2="55.88" y2="50.8" width="0.1524" layer="91"/>
                <label x="55.88" y="50.8" size="1.778" layer="95" rot="R0">GND</label>
              </segment>
            </net>
          </nets>
        </sheet>
      </sheets>
    </schematic>
  </drawing>
</eagle>
