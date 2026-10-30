// JScript 檔

// ==============================================================================================================
// 	實作 AJAX 的  AjaxRequest() 物件含Mozilla
// ==============================================================================================================

    
    function AjaxRequest()
    { 
	    var A=null;

	    // Internet Explorer
	    try
	    {
		    A=new ActiveXObject("Msxml2.XMLHTTP");
	    }
	    catch(e)
	    {
		    try
		    {
			    A=new ActiveXObject("Microsoft.XMLHTTP");
		    }
		    catch(oc)
		    {
			    A=null;
		    }
	    }

	    // Mozilla
	    if ( !A && typeof XMLHttpRequest != "undefined" ) 
	    {
		    A=new XMLHttpRequest();
	    }
	    return A;
    }
    
// ==============================================================================================================
// 	實作 取亂數 的 Rnd() 方法
// ==============================================================================================================
    function Rnd()
    {
        var theDate = new Date();

        return theDate.getMinutes() + "" + theDate.getSeconds() + "" + theDate.getMilliseconds() + "" + Math.floor(Math.random()*10000000000000000);
    }
    
// ==============================================================================================================
// 	選取 INPUT 元件 selected
// ==============================================================================================================       
      
    function ListSelected(objElement, SelectedValue)
    {
       
        for (var i=0; i<objElement.length; i++)
        {
	       
	        if ((objElement.options[i].value + "") == (SelectedValue + ""))
	        {
		        objElement.options[i].selected = true;
		        break;
	        }
        }
    }

// ==============================================================================================================
// 	實作 ASP 的 Request.QueryString 物件
// ==============================================================================================================   
    function aspRequest()
    {
        var urlpath, urlhash, urlary, varname, varval;
        var url = document.URL;
        var urlfile = (url + "?").split("?")[0];
        var urlquerystring = url.replace(urlfile, "");
        var s = urlfile.indexOf(":");
        var e = urlfile.lastIndexOf("/") + 1;

        s += 3;
        s = urlfile.indexOf("/", s);

        this.host = urlfile.substring(0, s);

        urlpath = urlfile.substring(s, e);
        urlfile = urlfile.substring(e, urlfile.length);
        urlquerystring = urlquerystring.replace("?", "");

        s = urlquerystring.lastIndexOf("#");

        if (s >= 0)
        {
	        urlhash = urlquerystring.substring((s+1), urlquerystring.length);
	        urlquerystring = urlquerystring.substring(0, s);
        }
        else
        {
	        urlhash = "";
        }

        urlary = ("&" + urlquerystring).split("&");

        this.path = urlpath;
        this.file = urlfile;
        this.hash = urlhash;
        this.aryQueryString = new Array();

        for (var i=1; i<urlary.length; i++)
        {
	        varname = (urlary[i] + "=").split("=")[0];
	        varval = urlary[i].replace(varname + "=", "");
	        varname = varname.toLowerCase();

	        if (this.aryQueryString[varname])
		        this.aryQueryString[varname] += "," + varval;
	        else
		        this.aryQueryString[varname] = varval;
        }

        this.QueryString = function (strQuery) {

	        if (strQuery && strQuery != "")
	        {
		        strQuery = strQuery.toLowerCase();

		        if (this.aryQueryString[strQuery])
			        return this.aryQueryString[strQuery];
		        else
			        return "";
	        }
	        else
	        {
		        return urlquerystring;
	        }
        }
    }
    
    
// ==============================================================================================================
// 	檢查輸入框是否為數值
// ============================================================================================================== 
    
    function CheckNum(obj_id)
    {
      if(obj_id.value=="")
      {
         alert("請輸入正確數值");
      }
      else
      {
          if(isNaN(obj_id.value) == false)
          {
             return true;
          }
          else
          {
             alert("請輸入正確數值");
             obj_id.focus();
	         return false;
          }
      }
    }
    