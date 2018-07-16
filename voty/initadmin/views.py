# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin views/actions
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib import messages
from django.contrib.sites.models import Site
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.conf import settings
from django.db.models import Q
from django.db.models.functions import Upper
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.translation import ugettext as _
from django.utils import six
from django.utils.html import escape, strip_tags
from django.views.decorators.http import require_POST

import account.views
from account.models import SignupCodeResult, SignupCode

from .models import InviteBatch
from .forms import (UploadFileForm, LoginEmailOrUsernameForm, UserEditForm,
  UserModerateForm, ListboxSearchForm, UserLocaliseForm, UserInviteForm,
  DeleteSignupCodeForm)

from datetime import datetime, timedelta
from uuid import uuid4
from dal import autocomplete
from io import StringIO, TextIOWrapper
import csv


# Poor man's decorator, use: @group_required("[group-name]")
# https://djangosnippets.org/snippets/10508/
def group_required(group, login_url=None, raise_exception=False):
  def check_perms(user):
    if isinstance(group, six.string_types):
      groups = (group, )
    else:
      groups = group

    if user.groups.filter(name__in=groups).exists():
      return True

    if raise_exception:
        raise PermissionDenied
    return False
  return user_passes_test(check_perms, login_url=login_url)

def _invite_single_user(first_name, email_address, site):
   
  try:
    code = SignupCode.objects.get(email=email_address)
    new_addition = False

  # XXX a bit lame to catchall including invalid (expired) codes. For now...
  except (SignupCode.DoesNotExist, SignupCode.InvalidCode):
    code = SignupCode(
      email=email_address,
      code=uuid4().hex[:20],
      max_uses=1,
      sent=datetime.utcnow(),
      expiry=datetime.utcnow() + timedelta(days=1)
    )
    new_addition = True
    code.save()

    EmailMessage(
      render_to_string("initadmin/email_invite_subject.txt"),
      render_to_string(
        "initadmin/email_invite_message.txt",
        context=dict(
          domain=site.domain,
          code=code,
          first_name=first_name,
          platform_title=settings.PLATFORM_TITLE
        )
      ),
      settings.DEFAULT_FROM_EMAIL,
      [email_address]
    ).send()
  

  return code, new_addition

def _invite_batch_users(csv_file):
  site = Site.objects.get_current()
  total = newly_added = 0
  reader = list(csv.reader(csv_file, delimiter=";"))
  results = StringIO()

  # create file for InviteBatch
  writer = csv.DictWriter(
    results,
    delimiter=";",
    fieldnames=["first_name", "last_name", "email_address", "invite_code"]
  )
  writer.writeheader()

  for row in reader:
    total += 1
    first_name = row[0]
    last_name = row[1]
    email_address = row[2]

    sent_with_code, new_addition = _invite_single_user(first_name, email_address, site)

    if new_addition:
      newly_added += 1

    writer.writerow({
      "first_name": first_name,
      "last_name": last_name,
      "email_address": email_address,
      "invite_code": sent_with_code.code
    })

  InviteBatch(
    payload=results.getvalue(),
    total_found=total,
    new_added=newly_added
  ).save()

  return total, newly_added

#
# ____    ____  __   ___________    __    ____   _______.
# \   \  /   / |  | |   ____\   \  /  \  /   /  /       |
#  \   \/   /  |  | |  |__   \   \/    \/   /  |   (----`
#   \      /   |  | |   __|   \            /    \   \    
#    \    /    |  | |  |____   \    /\    / .----)   |   
#     \__/     |__| |_______|   \__/  \__/  |_______/    
#
#                                                       

# ---------------------- SignupCode (Autocomplete) -----------------------------
class SignupCodeAutocomplete(autocomplete.Select2QuerySetView):

  def get_queryset(self):
    if not self.request.user.is_authenticated():
      return SignupCode.objects.none()

    qs = SignupCode.objects.all()
    if self.q:
      qs = qs.filter(email__icontains=self.q)
    return qs

  def get_result_label(self, item):
    return render_to_string(
      "fragments/autocomplete/signupcode_item.html",
      context=dict(item=item)
    )

# ---------------------------- Invite Users ------------------------------------
# XXX improve handling of multiple forms
@login_required
def user_invite(request):

  if request.method == "POST":

    # inviting single user
    if request.POST.get("action", None) == "invite_user":
      form = UserInviteForm(request.POST)
      if form.is_valid():
        email_address = request.POST.get("email")
        code, is_new = _invite_single_user(
          request.POST.get("first_name"),
          email_address,
          Site.objects.get_current()
        )
        if is_new == True:
          messages.success(request, "".join([_("Invitation sent to"), ": ", "{}".format(email_address)]))
        else:
          messages.warning(request, _("Could not send invitation. Please remove existing signup code first."))

    # inviting batch user
    elif request.POST.get("action", None) == "invite_batch":
      form = UploadFileForm(request.POST, request.FILES)
      if form.is_valid():
        total, sent = _invite_batch_users(TextIOWrapper(request.FILES['file'].file, encoding=request.encoding))
        messages.success(request, "".join(["{}/{} ".format(sent, total), _("(sent/total) invitations were sent.")]))

    # removing single signup code
    elif  request.POST.get("action", None) == "delete_signup":
      form = DeleteSignupCodeForm(request.POST)
      if form.is_valid():
        id = request.POST.get("id")
        signup = SignupCode.objects.get(id=id)
        email = signup.email
        signup.delete()
        messages.success(request, "".join([_("Removed Signup Code for"), ": ", "{}".format(email)]))

    return redirect("/backoffice/invite/")
  else:
    form_upload = UploadFileForm()
    form_invite = UserInviteForm()
    form_remove = DeleteSignupCodeForm()

  return render(request, "initadmin/invite_users.html", context={
    "form_upload": form_upload,
    "form_invite": form_invite,
    "form_remove": form_remove,
    "invitebatches": InviteBatch.objects.order_by("-created_at")
  })

# -------------------------- Delete Invitations --------------------------------
# XXX if we cannot delete, it will be impossible to re-invite someone. The whole 
# batch/signup code handling isn't very flexible.
@login_required
def delete_csv(request, batch_id):
  batch = get_object_or_404(InviteBatch, pk=batch_id)
  if batch:
    err_count = 0
    total_count = 0
    for invite in batch.payload.splitlines()[1:]:
      total_count += 1
      try:
        SignupCode.objects.get(email=invite.split(";")[2]).delete()
      except SignupCode.DoesNotExist:
        err_count += 1
        pass

  batch.delete()
  messages.success(request, "".join([
    "{} ".format(total_count),
    _("Signup Codes removed. Batch file deleted."),
    " ({} ".format(err_count),
    _("Codes could not be found"),
    ")"
  ]))

  return redirect("/backoffice/invite/")
  
# ------------------------- Download Invitations -------------------------------
@login_required
def download_csv(request, batch_id):
  batch = get_object_or_404(InviteBatch, pk=batch_id)
  response = HttpResponse(batch.payload, content_type="text/csv")
  response["Content-Disposition"] = "attachment; filename=invited_users.csv"
  return response

# -------------------------- Moderate User  ------------------------------------
@login_required
#@group_required("Policy Team", "Policy Team Lead")
def user_view(request, user_id):

  user_values = {"groups": []}
  user = get_object_or_404(get_user_model(), pk=user_id)

  if request.method == "GET":

    for group in Group.objects.all():
      if user.groups.filter(name=group.name).exists():
        user_values["groups"].append(group.id)

    user_values["username"] = user.username
    user_values["first_name"] = user.first_name
    user_values["last_name"] = user.last_name
    user_values["last_login"] = user.last_login.strftime("%Y-%m-%d %H:%M:%S (%Z)")
    user_values["email"] = user.email
    user_values["scope"] = user.config.scope
    user_values["is_scope_confirmed"] = user.config.is_scope_confirmed

  form = UserModerateForm(initial=user_values)

  # confirm allocation

  return render(request, "initadmin/moderate_user.html", context=dict(
    form=form,
    user=user
  ))

# ---------------------------- User List  --------------------------------------
# XXX make generic so it can be used for initiatives, too
@login_required
#@user_passes_test(lambda u: is_team_member(u))
def user_list(request):

  user_values = {}
  user_list = get_user_model().objects.filter()
  user_filters = {
    "glossary_active_all": True,
    "glossary_char_list": settings.LISTBOX_OPTION_DICT.GLOSSARY_CHAR_LIST
  }
  number_of_records = settings.LISTBOX_OPTION_DICT.NUMBER_OF_RECORDS_DEFAULT

  if "scope" in request.GET:
    request_scope = request.GET["scope"]
    for scope in settings.CATEGORIES.SCOPE_CHOICES:
      if scope[0] == request_scope:
        user_list = user_list.filter(config__scope__istartswith=request_scope).distinct()
        user_values["scope"] = request_scope

  if "search" in request.GET:
    request_search = escape(strip_tags(request.GET["search"]))
    user_list = user_list.filter(
      Q(first_name__icontains=request_search) |
      Q(last_name__icontains=request_search) |
      Q(username__icontains=request_search) |
      Q(email__icontains=request_search)
    ).distinct()
    user_values["search"] = request_search

  # XXX glossary assumes we are searching for username, should be settable
  # XXX missing summarizing all $%&/( into #
  # by now we have the relevant user set, flag available characters
  glossary_candidate_list = [getattr(x[1], "username", None) for x in enumerate(user_list)]
  glossary_candidate_list = list(set([x[0].upper() for x in glossary_candidate_list if x is not None]))

  for glossy_character in glossary_candidate_list:
    try:
      user_filters["glossary_char_list"][glossy_character]["avail"] = True
    except:
      user_filters["glossary_char_list"]["#"]["avail"] = True

  # filter user_list if a glossary is passed in the request
  if "glossary" in request.GET:
    request_glossy_character = request.GET["glossary"]
    if request_glossy_character != "":
      regex_azAZ = r"^[a-zA-Z]"
    
      # XXX refactor
      # XXX why are active chars sticky and a reload does not remove them?
      for glossy_character in glossary_candidate_list:
        if glossy_character == request_glossy_character:
          if request_glossy_character == "#":
            user_list = user_list.exclude(username__regex=regex_azAZ)
            del user_filters["glossary_char_list"]["#"]["avail"]
            del user_filters["glossary_active_all"]
          else:
            user_list = user_list.filter(username__istartswith=glossy_character)
            del user_filters["glossary_char_list"][glossy_character]["avail"]
            del user_filters["glossary_active_all"]

  # always convert glossary_char_list into parseable format
  user_filters["glossary_char_list"] = [user_filters["glossary_char_list"][x] for x in user_filters["glossary_char_list"]]

  # XXX sorting defaults to username, add sorting, add default/asc/desc to settings
  if "sort" in request.GET:
    pass
    #request_sort = request.GET["sort"]
    #for sortation in settings.SORT_OPITION_LIST:
    #  if request_sort["field"] == sortation
    #    if request_sort["dir"] == "DESC":
    #      user_list.order_by(request_sort).reverse()
    #    else:
    #      user_list.order_by(request_sort)
    #user_values["sort"] = request_sort
  else:
    user_list = user_list.order_by("username")

  if "records" in request.GET:
    request_records = request.GET["records"]
    if request_records.isdigit():
      for record_opt in settings.LISTBOX_OPTION_DICT.NUMBER_OF_RECORDS_OPTION_LIST:
        if record_opt[0] == request_records:
          number_of_records = request_records
          user_values["records"] = request_records

  paginator = Paginator(user_list, number_of_records)
  page = request.GET.get("page")
  form = ListboxSearchForm(initial=user_values)
    
  try:
    users = paginator.page(page)
  except PageNotAnInteger:
    users = paginator.page(1)
  except EmptyPage:
    users = paginator.page(paginator.num_pages)

  return render(request, "initadmin/list_users.html", {
    "paginator": paginator,
    "users" :users,
    "user_filters": user_filters,
    "form": form
    }
  )

# -------------------------- Notification List  --------------------------------
def notification_list(request):
  return render(request)

# -------------------------- Initiative List  ----------------------------------
def initiative_list(request):
  return render(request, "Hello Initiative List", context={})

# --------------------------- Localise User ------------------------------------
@login_required
def profile_localise(request):

  user = get_object_or_404(get_user_model(), id=request.user.id)

  if request.method == "POST":
    form = UserLocaliseForm(request.POST)
    if form.is_valid():

      # XXX explicitly unset?
      form = UserLocaliseForm(request.POST, instance=user.config)
      form.save()

      # trigger a notification which only custom groups can see
      # notification should be like worklist = localisations to validate (13)
      # flag this user in the user list
      # make a filter for flagged users
  else:
    user_values = {
      "scope": user.config.scope,
      "is_scope_confirmed": user.config.is_scope_confirmed
    }
    form = UserLocaliseForm(initial=user_values)

  return render(request, "account/localise.html", {"form":form, "user": user})


# ---------------------------- LoginView ---------------------------------------
# XXX why is it a class? can't this be just a form?
class LoginView(account.views.LoginView):
  form_class = LoginEmailOrUsernameForm

# --------------------------- Profile Edit -------------------------------------
@login_required
def profile_edit(request):
  user = get_object_or_404(get_user_model(), pk=request.user.id)
  if request.method == "POST":
    form = UserEditForm(request.POST, instance=user)
    if form.save():
      messages.success(request, _("Data updated."))
  else:
    form = UserEditForm(instance=user)

  return render(request, "account/profile_edit.html", context=dict(form=form))

# --------------------------- Profile Delete -----------------------------------
def profile_delete(request):
  return render(request, "initadmin/delete.html", context={})


# active users (recently logged in first)
#@login_required
#def active_users(request):
#    users_q = get_user_model().objects.filter(is_active=True, avatar__primary=True).order_by("-last_login")
#    return render(request, "initadmin/active_users.html", dict(users=users_q))

