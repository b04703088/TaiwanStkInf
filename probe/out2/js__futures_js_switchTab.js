// ­¶ÅÒ¤Á´«®ÄªG
function switchTab(tab_title, pst, tab_cnt)
{
	for(var i=0 ; i<tab_cnt ; i++)
	{
		if (i == pst)
			document.getElementById(tab_title+'_tab_'+i).className = 'current';
		else
			document.getElementById(tab_title+'_tab_'+i).className = '';
		if (i == pst)
			document.getElementById(tab_title+'_'+i).className = 'disyshow';
		else
			document.getElementById(tab_title+'_'+i).className = 'disyhidn';
	}
}

var sw=false;
function p(o) {
	sw=!sw;
	o.className = (sw)?'idxselect on':'idxselect off';
}
function s(o) {
	document.getElementById('lnk').innerHTML = o.innerHTML;
	return false;
}

function switchTab2(tab_title2, pst2, tab_cnt2)
{
	if (document.getElementById("cyadsclose").className == "disyshow")
	{
	    for(var i=0 ; i<tab_cnt2 ; i++)
	    {
		    if (i == pst2)
			    document.getElementById(tab_title2+'_tab_'+i).className = 'current';
		    else
			    document.getElementById(tab_title2+'_tab_'+i).className = '';
		    if (i == pst2)
			    document.getElementById(tab_title2+'_'+i).className = 'disyshow';
		    else
			    document.getElementById(tab_title2+'_'+i).className = 'disyhidn';
	    }
	}
}


function divclose(tab_title2, pst2, tab_cnt2)
{
	if (document.getElementById("cyadsclose").className == "disyhidn")
	{   document.getElementById("cyadsclose").className="disyshow"
	    for(var i=0 ; i<tab_cnt2 ; i++)
	    {
		    if (i == pst2)
			    document.getElementById(tab_title2+'_tab_'+i).className = 'current';
		    else
			    document.getElementById(tab_title2+'_tab_'+i).className = '';
		    if (i == pst2)
			    document.getElementById(tab_title2+'_'+i).className = 'disyshow';
		    else
			    document.getElementById(tab_title2+'_'+i).className = 'disyhidn';
	    }	
	}
	else
	{
        document.getElementById("cyadsclose").className = "disyhidn"
	    for(var i=0 ; i<tab_cnt2 ; i++)
	    {
   	     document.getElementById(tab_title2+'_tab_'+i).className = '';

	    }	        
	}
	
}