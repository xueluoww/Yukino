/* A reader-facing greeting only; no API request or change of story state. */
(function () {
  'use strict';
  var field = document.getElementById('player-name');
  var dialog = document.getElementById('name-easter-dialog');
  var close = document.getElementById('close-name-easter');
  if (!field || !dialog || !close) return;
  var greeted = false;
  function checkName() {
    var match = field.value.trim() === 'xlww';
    if (!match) { greeted = false; return; }
    var pane = document.getElementById('new-story-pane');
    var picker = document.getElementById('story-picker');
    if (greeted || !pane || pane.hidden || !picker || picker.hidden || dialog.open) return;
    greeted = true;
    dialog.showModal();
  }
  field.addEventListener('input', checkName);
  field.addEventListener('change', checkName);
  close.addEventListener('click', function () { dialog.close(); field.focus(); });
}());
