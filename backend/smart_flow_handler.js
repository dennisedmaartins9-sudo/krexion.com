/*SMART_FLOW v4 — full funnel + deal wall + URL deal sync */
(function () {
  window.__krxDealsDone = window.__krxDealsDone || 0;
  window.__krxDealKeys = window.__krxDealKeys || {};

  function rfFire(el) {
    if (!el) return;
    var r = el.getBoundingClientRect();
    var x = r.left + r.width / 2,
      y = r.top + r.height / 2;
    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(function (t) {
      try {
        var ev =
          t.indexOf("pointer") === 0
            ? new PointerEvent(t, { bubbles: true, cancelable: true, clientX: x, clientY: y })
            : new MouseEvent(t, { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0 });
        el.dispatchEvent(ev);
      } catch (e) {}
    });
    try {
      el.click();
    } catch (e) {}
  }
  function isVis(e) {
    if (!e) return false;
    var s = window.getComputedStyle(e);
    if (s.display === "none" || s.visibility === "hidden" || s.pointerEvents === "none") return false;
    var r = e.getBoundingClientRect();
    return r.width >= 20 && r.height >= 10;
  }
  function visInput(e) {
    if (!isVis(e)) return false;
    var r = e.getBoundingClientRect();
    return r.width > 40 && r.height > 18;
  }
  function txt(e) {
    return ((e.innerText || e.textContent || e.value || "") + "").trim();
  }
  function btns() {
    return Array.from(document.querySelectorAll("button,a,div,span,[role=button]")).filter(isVis);
  }
  function syncUrlDeals() {
    var u = location.href;
    var n = 0;
    if (/BVA=True/i.test(u)) n++;
    if (/BVB=True/i.test(u)) n++;
    if (/BVC=True/i.test(u)) n++;
    if (/BVD=True/i.test(u)) n++;
    if (/BVE=True/i.test(u)) n++;
    window.__krxDealsDone = Math.max(window.__krxDealsDone || 0, n);
  }
  function cleanNum(v, pad) {
    v = String(v == null ? "" : v).trim().replace(/\.0+$/, "");
    if (/^\d+\.\d+$/.test(v)) v = v.split(".")[0];
    var n = parseInt(v, 10);
    if (isNaN(n)) return v;
    return pad ? String(n).padStart(pad, "0") : String(n);
  }
  function cleanZip(z) {
    z = String(z == null ? "" : z).trim();
    if (/^\d+\.0+$/.test(z)) z = z.replace(/\.0+$/, "");
    if (/^\d+\.\d+$/.test(z)) z = z.split(".")[0];
    z = z.replace(/[^\d]/g, "");
    return z.length >= 5 ? z.slice(0, 5) : z;
  }
  function cleanPhone(p) {
    return String(p == null ? "" : p).replace(/\D/g, "");
  }
  function setVal(el, v) {
    if (!el || v == null || v === "") return;
    try {
      el.focus();
    } catch (e) {}
    var nat = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    try {
      if (nat && nat.set) nat.set.call(el, v);
      else el.value = v;
    } catch (e) {
      el.value = v;
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    try {
      el.blur();
    } catch (e) {}
  }
  function typeInto(el, v) {
    if (!el || v == null || v === "") return;
    try {
      el.focus();
      el.click();
    } catch (e) {}
    setVal(el, "");
    String(v).split("").forEach(function (ch) {
      el.dispatchEvent(new KeyboardEvent("keydown", { key: ch, bubbles: true }));
      el.value += ch;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new KeyboardEvent("keyup", { key: ch, bubbles: true }));
    });
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function setSelect(sel, val) {
    if (!sel || val == null || val === "") return;
    var v = String(val).trim();
    var vNum = cleanNum(v, 0);
    sel.value = v;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    if (sel.value === v || sel.value === vNum) return;
    var opts = Array.from(sel.options || []);
    var m = opts.find(function (o) {
      var ov = (o.value || "").trim();
      var ot = (o.text || "").trim();
      return ov === v || ov === vNum || ot === v || ot === vNum;
    });
    if (m) {
      sel.value = m.value;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  function hasFormErrors() {
    var btl = (document.body.innerText || "").toLowerCase();
    return /please enter a zip|please complete date of birth|please enter.*valid|invalid zip|invalid email|field is required|this field is required/.test(
      btl
    );
  }
  function visibleFormActive() {
    var fn = document.querySelector("#lfirstname,#firstname,input[name*='first' i]");
    if (!fn || !visInput(fn)) return false;
    var visibleInputs = Array.from(
      document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio])")
    ).filter(visInput);
    return visibleInputs.length >= 3;
  }
  function isDealPage(bt, host) {
    var hasBestMatch = /best match for you/i.test(bt);
    var hasMustComplete = /you must complete\s*\d+\s*deal/i.test(bt);
    var hasNextStep = /next step:.{0,40}complete\s*\d+\s*deal/i.test(bt);
    var hasCost = /your cost:\s*\$|minimum\s*deposit|free trial/i.test(bt);
    var dealHost = /uplevelrewards|levelrewards|rewardsgiant|deals\.|getmy/i.test(host);
    var contBtns = btns().filter(function (e) {
      var t = txt(e);
      return t === "CONTINUE" || t === "Continue";
    });
    if (visibleFormActive()) return false;
    if (hasBestMatch || hasMustComplete || hasNextStep) return true;
    if (dealHost && (hasCost || contBtns.length >= 1)) return true;
    if (hasCost && contBtns.length >= 2) return true;
    if (/fillwords|justplay|bingo billions|reward offer/i.test(bt) && contBtns.length >= 1) return true;
    return false;
  }
  function handleDealPage(bt) {
    if (/do you already have/i.test(bt)) {
      var modal = btns().find(function (e) {
        var t = txt(e).toUpperCase();
        return t === "NO" || t === "NO!";
      });
      if (modal) {
        rfFire(modal);
        return true;
      }
    }
    var dealBtns = btns().filter(function (e) {
      var t = txt(e);
      return t === "CONTINUE" || t === "Continue";
    });
    for (var i = 0; i < dealBtns.length; i++) {
      var b = dealBtns[i];
      var key = (b.href || "") + "|" + txt(b) + "|" + Math.round(b.getBoundingClientRect().top);
      if (window.__krxDealKeys[key]) continue;
      window.__krxDealKeys[key] = 1;
      window.__krxDealsDone = (window.__krxDealsDone || 0) + 1;
      rfFire(b);
      return true;
    }
    return false;
  }
  function tryNavigateDealWall() {
    var host = (location.host || "").toLowerCase();
    if (!/displayoptoffers|uplevelrewards|levelrewards|retailproductsusa/i.test(host)) return false;
    var anchors = Array.from(document.querySelectorAll("a[href]")).filter(function (a) {
      if (!isVis(a)) return false;
      var h = (a.href || "").toLowerCase();
      return /uplevelrewards|levelrewards|rewardsgiant|getmy|deals\.|complete.*deal/i.test(h);
    });
    if (anchors.length) {
      rfFire(anchors[0]);
      return true;
    }
    var cta = btns().find(function (e) {
      var t = txt(e).toLowerCase();
      return /start earning|view deal|complete deal|get my reward|claim reward|see offer|explore deal|reward status|member support/i.test(t) === false &&
        /start earning|view deal|complete deal|get my reward|claim reward|see offer|explore deal|continue to deal|go to deal/i.test(t);
    });
    if (cta) {
      rfFire(cta);
      return true;
    }
    return false;
  }
  function pickVisibleSurveyAnswer() {
    var ANSWER =
      /^(often|rarely|never|sometimes|daily|weekly|monthly|today|past 2 weeks|this month|over a month ago|yes|no|yes!|no!|i'?m not|not on medicare|none of the above)$/i;
    var LONG =
      /^(silent generation|baby boomer|gen x|millennial|gen z|puzzle|role playing|casino|classic \(board)/i;
    var seen = {};
    var candidates = btns()
      .filter(function (e) {
        var t = txt(e);
        if (!t || t.length > 90 || t.length < 2) return false;
        if (/skip the survey|about the survey|privacy|terms|faq|member support|unsubscribe|program requirements/i.test(t)) return false;
        var r = e.getBoundingClientRect();
        if (r.top < 40 || r.top > window.innerHeight * 0.92) return false;
        if (r.width < 55 || r.height < 28) return false;
        if (!ANSWER.test(t) && !LONG.test(t) && !/born 19|born 20|\(born/i.test(t)) return false;
        var key = t.toLowerCase();
        if (seen[key]) return false;
        seen[key] = 1;
        return true;
      })
      .sort(function (a, b) {
        return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
      });
    return candidates[0] || null;
  }
  function fillDob(data) {
    var month = cleanNum(data.month, 2);
    var day = cleanNum(data.day, 2);
    var year = cleanNum(data.year, 0);
    if (!month || !day || !year) return;
    setSelect(document.querySelector("select[name=dobmonth],select#ldobmonth,select[name*='dobmonth' i]"), month);
    setSelect(document.querySelector("select[name=dobday],select#ldobday,select[name*='dobday' i]"), day);
    setSelect(document.querySelector("select[name=dobyear],select#ldobyear,select[name*='dobyear' i]"), year);
    var mIn = document.querySelector("input[placeholder='Month'],input[name='dobmonth'],input#ldobmonth");
    var dIn = document.querySelector("input[placeholder='Day'],input[name='dobday'],input#ldobday");
    var yIn = document.querySelector("input[placeholder='Year'],input[name='dobyear'],input#ldobyear");
    if (mIn && visInput(mIn)) typeInto(mIn, month);
    if (dIn && visInput(dIn)) typeInto(dIn, day);
    if (yIn && visInput(yIn)) typeInto(yIn, year);
    var all = Array.from(document.querySelectorAll("*"));
    var labelEl = null;
    for (var i = 0; i < all.length; i++) {
      var lt = (all[i].innerText || all[i].textContent || "").trim();
      if (/^date of birth$|^d\.?o\.?b\.?$/i.test(lt) && lt.length < 30) {
        labelEl = all[i];
        break;
      }
    }
    if (labelEl) {
      var lr = labelEl.getBoundingClientRect();
      var near = Array.from(document.querySelectorAll("input")).filter(function (e) {
        if (!isVis(e)) return false;
        var er = e.getBoundingClientRect();
        return er.top >= lr.top - 15 && er.top <= lr.bottom + 150 && er.width > 30;
      });
      near.sort(function (a, b) {
        return a.getBoundingClientRect().left - b.getBoundingClientRect().left;
      });
      if (near.length >= 3) {
        typeInto(near[0], month);
        typeInto(near[1], day);
        typeInto(near[2], year);
      }
    }
  }

  syncUrlDeals();
  var bt = (document.body.innerText || "").toLowerCase();
  var host = (location.host || "").toLowerCase();
  var url = location.href || "";

  /* 1. DEAL PAGE */
  if (isDealPage(bt, host)) {
    if (handleDealPage(bt)) return;
  }

  /* 2. Navigate to deal wall after form done */
  if ((/isULUDone=True/i.test(url) || /isUserLookUp=True/i.test(url)) && (window.__krxDealsDone || 0) < 2) {
    if (tryNavigateDealWall()) return;
  }

  /* 3. ACTIVE SURVEY */
  var onActiveSurvey =
    /finish your survey|credit\/debit card|how often do you|homeowner|online purchase|when did you last|generation do you|games do you like|survey to proceed|are you a homeowner/.test(
      bt
    );
  if (onActiveSurvey) {
    var surveyPick = pickVisibleSurveyAnswer();
    if (surveyPick) {
      rfFire(surveyPick);
      return;
    }
  }

  /* 4. LEAD FORM */
  function findVis(sel) {
    var el = document.querySelector(sel);
    return el && visInput(el) ? el : null;
  }
  var fn =
    findVis("#lfirstname") ||
    findVis("#firstname") ||
    findVis("input[name*='first' i]") ||
    findVis("input[placeholder*='First' i]");
  var visibleInputs = Array.from(
    document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio])")
  ).filter(visInput);
  var onLeadForm =
    fn &&
    visibleInputs.length >= 3 &&
    !/confirming your email|sign up or resume by confirming|your reward is waiting/i.test(bt) &&
    !onActiveSurvey;

  if (onLeadForm) {
    var raw = {
      first: "{{first}}",
      last: "{{last}}",
      address: "{{address}}",
      zip: "{{zip_code}}",
      city: "{{city}}",
      state: "{{state}}",
      phone: "{{cellphone}}",
      email: "{{email}}",
      gender: "{{gender}}",
      day: "{{day}}",
      month: "{{month}}",
      year: "{{year}}",
    };
    var data = {
      first: String(raw.first || "").trim(),
      last: String(raw.last || "").trim(),
      address: String(raw.address || "").trim(),
      zip: cleanZip(raw.zip),
      city: String(raw.city || "").trim(),
      state: String(raw.state || "").trim().toUpperCase(),
      phone: cleanPhone(raw.phone),
      email: String(raw.email || "").trim(),
      gender: String(raw.gender || "").trim().toLowerCase(),
      day: cleanNum(raw.day, 2),
      month: cleanNum(raw.month, 2),
      year: cleanNum(raw.year, 0),
    };
    var used = new Set();
    function findBy(re, emailType) {
      var inputs = visibleInputs.filter(function (e) {
        return !used.has(e);
      });
      var match = inputs.find(function (e) {
        if (emailType && (e.type || "").toLowerCase() === "email") return true;
        return re.test(e.name || "") || re.test(e.id || "") || re.test(e.placeholder || "") || re.test(e.getAttribute("aria-label") || "");
      });
      if (match) used.add(match);
      return match;
    }
    setVal(findBy(/email|e-mail/i, true), data.email);
    setVal(findBy(/first.*name|firstname|^first$|fname|lfirstname/i), data.first);
    setVal(findBy(/last.*name|lastname|^last$|lname|surname|llastname/i), data.last);
    setVal(findBy(/street|^address$|address(?!.*2)|addr|laddress/i), data.address);
    setVal(findBy(/^zip|postal|zipcode|lzip/i), data.zip);
    setVal(findBy(/city|town|lcity/i), data.city);
    if (data.phone.length >= 10) {
      setVal(findVis("#lphonecode") || findVis("#phonecode"), data.phone.slice(0, 3));
      setVal(findVis("#lphoneprefix") || findVis("#phoneprefix"), data.phone.slice(3, 6));
      setVal(findVis("#lphonesuffix") || findVis("#phonesuffix"), data.phone.slice(6, 10));
    }
    setVal(findBy(/phone|mobile|cell|tel(?!nology)/i), data.phone);
    var sel = document.querySelector("select[name*='state' i],select[id*='state' i],select#lstate");
    if (sel && isVis(sel)) setSelect(sel, data.state);
    fillDob(data);
    if (data.gender) {
      var gBtn = btns().find(function (e) {
        return txt(e).toLowerCase() === data.gender;
      });
      if (gBtn) rfFire(gBtn);
    }
    var cb = document.querySelector("input[type=checkbox]");
    if (cb && !cb.checked) {
      cb.checked = true;
      cb.dispatchEvent(new Event("change", { bubbles: true }));
      try {
        cb.click();
      } catch (e) {}
    }
    if (!hasFormErrors()) {
      var formCont = btns().filter(function (e) {
        var t = txt(e).toLowerCase();
        var r = e.getBoundingClientRect();
        return r.width >= 80 && r.height >= 30 && (t === "continue" || t.indexOf("continue") === 0 || t === "submit" || t === "next");
      });
      if (formCont.length) rfFire(formCont[formCont.length - 1]);
    }
    return;
  }

  /* 5. EMAIL POPUP */
  if (/your reward is waiting|ready to go|we use email|enter your email|confirming your email|sign up or resume|confirm your email/i.test(bt)) {
    var emailIn = document.querySelector("input[type=email],input#email,input[name*=email i]");
    if (emailIn && visInput(emailIn)) setVal(emailIn, "{{email}}");
    var cont = btns().find(function (e) {
      return /^continue$/i.test(txt(e));
    });
    if (cont) {
      rfFire(cont);
      return;
    }
  }

  /* 6. RETAIL SURVEY */
  if (/retailproductsusa/.test(host) || /question 1|do you shop at target|question 2|question 3|activating your reward/i.test(bt)) {
    if (/question 1|do you shop at target/.test(bt)) {
      var yn = btns().filter(function (e) {
        var t = txt(e).toLowerCase();
        return t === "yes" || t === "no";
      });
      if (yn.length) {
        rfFire(yn[Math.floor(Math.random() * yn.length)]);
        return;
      }
    }
    if (/question 2|what would you do/.test(bt)) {
      var q2 = btns().filter(function (e) {
        var t = txt(e).toLowerCase();
        return t.indexOf("use it myself") >= 0 || t.indexOf("share with family") >= 0;
      });
      if (q2.length) {
        rfFire(q2[Math.floor(Math.random() * q2.length)]);
        return;
      }
    }
    if (/question 3|weekly|monthly|activating your reward/.test(bt)) {
      var q3 = btns().filter(function (e) {
        var t = txt(e).toLowerCase();
        return t === "weekly" || t === "monthly";
      });
      if (q3.length) {
        rfFire(q3[Math.floor(Math.random() * q3.length)]);
        return;
      }
    }
    var cta = btns().find(function (e) {
      return /get a quick start|get started now|claim my|start earning/i.test(txt(e));
    });
    if (cta) {
      rfFire(cta);
      return;
    }
  }

  /* 7. SMS / EMAIL popups */
  if (/explore offers from our sponsors|from our sponsors|sign up for text|texted to you|status texted|text me reward|sms.{0,10}updates/.test(bt)) {
    var nt = btns().find(function (e) {
      var t = txt(e).toLowerCase();
      return t === "no thanks" || t === "no, thanks";
    });
    if (nt) {
      rfFire(nt);
      return;
    }
  }
  if (/emailed to you|status emailed|emailed status/.test(bt)) {
    var y = btns().find(function (e) {
      var t = txt(e).toLowerCase();
      return t === "yes!" || t === "yes";
    });
    if (y) {
      rfFire(y);
      return;
    }
  }

  if (isDealPage(bt, host)) return;

  var surveyPick2 = pickVisibleSurveyAnswer();
  if (surveyPick2) {
    rfFire(surveyPick2);
    return;
  }

  var isBank = /active bank account|bank account/.test(bt);
  function visibleEl(e) {
    return isVis(e) && e.getBoundingClientRect().width >= 40 && e.getBoundingClientRect().height >= 20;
  }
  var allClickable = Array.from(document.querySelectorAll("button,a,[role=button],input[type=button],input[type=submit],div,span")).filter(function (e) {
    if (!visibleEl(e)) return false;
    var t = txt(e);
    if (!t || t.length > 140 || t.length < 1) return false;
    var lc = t.toLowerCase();
    var FILTER = ["skip the survey", "about the survey", "privacy policy", "terms & conditions", "faq", "member support", "unsubscribe", "sign up now", "get started now", "claim my $750"];
    if (FILTER.indexOf(lc) >= 0) return false;
    return true;
  });
  var surveyBtns = allClickable.filter(function (e) {
    var t = txt(e);
    return (
      /^(yes|no|often|rarely|never|sometimes|today|weekly|monthly)$/i.test(t) ||
      /^(i'?m not|medicare|medicaid|none of|other|no obligation)/i.test(t)
    );
  });
  if (surveyBtns.length) {
    var pick = isBank
      ? surveyBtns.find(function (e) {
          return /^yes$/i.test(txt(e));
        }) || surveyBtns[0]
      : surveyBtns[Math.floor(Math.random() * surveyBtns.length)];
    rfFire(pick);
    return;
  }
  var noThx = allClickable.find(function (e) {
    return /^(no thanks|no, thanks|skip|cancel|maybe later|not now)$/i.test(txt(e).toLowerCase());
  });
  if (noThx) {
    rfFire(noThx);
    return;
  }
  var cont = allClickable.find(function (e) {
    return /^(continue|next|submit|proceed|got it|ok|okay)$/i.test(txt(e).toLowerCase());
  });
  if (cont) {
    rfFire(cont);
    return;
  }
  var anyBtn = allClickable.filter(function (e) {
    var t = txt(e);
    if (t.length > 50 || t.length < 2) return false;
    var r = e.getBoundingClientRect();
    return r.top > 0 && r.top < window.innerHeight * 1.5 && r.width >= 60 && r.height >= 25;
  });
  if (anyBtn.length) rfFire(anyBtn[Math.floor(Math.random() * Math.min(anyBtn.length, 3))]);
  syncUrlDeals();
})();
