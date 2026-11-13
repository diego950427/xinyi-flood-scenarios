const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),checks={},errors=[];
let browser;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 browser=await chromium.launch({headless:true,executablePath:process.env.COMPARISON_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1280,height:950}});page.on('pageerror',e=>errors.push(e.message));
 const url=process.argv[2]||'http://127.0.0.1:8518';await page.goto(url);
 await page.getByRole('tab',{name:'並排比較',exact:true}).click({timeout:60000});
 await page.getByRole('button',{name:'顯示比較',exact:true}).click();
 let frame;
 for(let n=0;n<45&&!frame;n++){
   for(const f of page.frames()){if(await f.evaluate(()=>!!window.__xinyiComparison?.getState().ready).catch(()=>false)){frame=f;break;}}
   if(!frame)await sleep(1000);
 }
 if(!frame)throw Error('Comparison iframe not ready');
 let s=await frame.evaluate(()=>window.__xinyiComparison.getState());
 checks.embedded_webgl=s.renderer==='webgl';checks.default_focus_is_xinyi=s.view.extent==='district';
 await frame.locator('#three').click();await sleep(150);checks.embedded_3d=(await frame.evaluate(()=>window.__xinyiComparison.getState())).view.mode==='3d';
 await page.screenshot({path:path.join(root,'qa/artifacts/comparison/app_desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await frame.locator('#top').click();await sleep(200);
 await frame.locator('#inspect').scrollIntoViewIfNeeded();
 checks.mobile_iframe_can_scroll=await frame.evaluate(()=>window.scrollY>0&&document.getElementById('inspect').getBoundingClientRect().bottom<=innerHeight+2);
 checks.mobile_iframe_no_horizontal_scroll=await frame.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
 await page.screenshot({path:path.join(root,'qa/artifacts/comparison/app_mobile.png'),fullPage:true});
 await page.setViewportSize({width:1280,height:950});
 const save=page.getByRole('button',{name:'保存互動比較（離線 HTML）',exact:true});
 const promise=page.waitForEvent('download');await save.click();const download=await promise;
 const file=path.join(root,'qa/artifacts/comparison/from_app.html');await download.saveAs(file);
 const html=fs.readFileSync(file,'utf8');checks.download_is_complete_offline_html=html.includes('comparison-data')&&html.includes('class WebGLRenderer')&&html.includes('兩筆條件');
 checks.no_app_exception=await page.locator('[data-testid="stException"]').count()===0;
 checks.no_browser_errors=errors.length===0;
 const report={passed:Object.values(checks).every(Boolean),checks,errors,url,checked_at:new Date().toISOString(),scope:'Actual browser in Streamlit; compare controls, mobile iframe scroll, offline download; no solver execution'};
 fs.writeFileSync(path.join(root,'qa/comparison_app_browser_tests.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 if(!report.passed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close()});
