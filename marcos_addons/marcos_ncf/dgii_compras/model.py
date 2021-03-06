# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2013-2015 Marcos Organizador de Negocios SRL http://marcos.do
#    Write by Eneldo Serrata (eneldo@marcos.do)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from openerp.osv import osv, fields
import base64
from openerp.tools.translate import _
import time


def _get_month(self, cursor, user_id, context=None):
    return (
       ('01', 'Enero'),
       ('02', 'Febrero'),
       ('03', 'Marzo'),
       ('04', 'Abril'),
       ('05', 'Mayo'),
       ('06', 'Junio'),
       ('07', 'Julio'),
       ('08', 'Agosto'),
       ('09', 'Septimbre'),
       ('10', 'Octubre'),
       ('11', 'Noviembre'),
       ('12', 'Diciembre')
    )


class purchase_report(osv.Model):
    """
    606 Purchase of Goods and Services report header.

    """

    _name = 'marcos.dgii.purchase.report'
    _inherit = ['mail.thread']

    def _line_count(self, cr, uid, ids, context=None):
        purchase_report_obj = self.pool.get('marcos.dgii.purchase.report')
        purchase_report = purchase_report_obj.browse(cr, uid, ids, context=context)[0]
        return len(purchase_report.purchase_report_line_ids)

    def _sum_amount(self, cr, uid, ids, field, context=None):
        purchase_report_obj = self.pool.get('marcos.dgii.purchase.report')
        purchase_report = purchase_report_obj.browse(cr, uid, ids, context=context)[0]
        res = 0
        for line in purchase_report.purchase_report_line_ids:
            res = res + line[field]
        return res

    def _get_updated_fields(self, cr, uid, ids, context=None):
        vals = {}
        vals['line_count'] = self._line_count(cr, uid, ids, context=context)
        vals['billed_amount_total'] = self._sum_amount(cr, uid, ids, u'MONTO_FACTURADO', context=context)
        vals['billed_tax_total'] = self._sum_amount(cr, uid, ids, u'ITBIS_PAGADO', context=context)
        vals['retained_tax_total'] = self._sum_amount(cr, uid, ids, u'ITBIS_RETENIDO', context=context)
        vals['retained_isr_total'] = self._sum_amount(cr, uid, ids, u'RETENCION_RENTA', context=context)
        return vals

    _columns = {
        'period_id': fields.many2one('account.period', u'Período', required=True),
        'subsidiary_id': fields.many2one('res.company.subsidiary', u'Compañia (RNC)', required=True),
        'subsidiary_ids': fields.many2many('res.company.subsidiary',
                                           'purchase_report_subsidiary_rel',
                                           'purchase_report_id',
                                           'subsidiary_id',
                                           'Subsidiaries', required=True),
        'line_count': fields.integer(u"Total de registros", readonly=True),
        'billed_amount_total': fields.float(u'Total Facturado', readonly=True),
        'billed_tax_total': fields.float(u'Total ITBIS Facturado', readonly=True),
        'retained_tax_total': fields.float(u'Total ITBIS Retenido', readonly=True),
        'retained_isr_total': fields.float(u'Total retenciones del ISR', readonly=True),
        'report': fields.binary(u"Reporte", readonly=True),
        'report_name': fields.char(u"Nombre de Reporte", 40, readonly=True),
        'purchase_report_line_ids': fields.one2many('marcos.dgii.purchase.report.line', 'purchase_report_id', u'Compras'),
        }

    _defaults = {
        'company_id': lambda self, cr, uid, c: self.pool.get('res.users').browse(cr, uid, uid, c).company_id.id,
        }

    def create(self, cr, uid, values, context=None):
        """
        Re-write to create purchases and to update read-only fields.

        """

        res = super(purchase_report, self).create(cr, uid, values, context=context)

        # Loads all purchases
        self.create_purchases(cr, uid, res, values['period_id'], context=context)

        # Update readonly fields
        vals = self._get_updated_fields(cr, uid, [res], context=None)
        self.write(cr, uid, [res], vals)
        return res

    def write(self, cr, uid, ids, vals, context=None):
        """
        Re-write to update read-only fields.

        """

        super(purchase_report, self).write(cr, uid, ids, vals, context)
        vals.update(self._get_updated_fields(cr, uid, ids, context=None))

        result = super(purchase_report, self).write(cr, uid, ids, vals, context)
        return result

    def re_create_purchases(self, cr, uid, ids, context=None):
        lines_obj = self.pool.get('marcos.dgii.purchase.report.line')
        report = self.browse(cr, uid, ids[0])
        line_ids = [line.id for line in report.purchase_report_line_ids]
        lines_obj.unlink(cr, uid, line_ids)

        result = self.create_purchases(cr, uid, report.id, report.period_id.id, context=context)

        vals = self._get_updated_fields(cr, uid, ids, context=None)
        self.write(cr, uid, ids, vals)

        return result

    def create_purchases(self, cr, uid, purchase_report_id, period_id, context=None):

        #pdb.set_trace()
        wizard = self.browse(cr, uid, purchase_report_id, context=context)

        tax_line_obj = self.pool.get('account.invoice.tax')
        tax_obj = self.pool.get('account.tax')
        invoice_obj = self.pool.get('account.invoice')
        cur_obj = self.pool.get('res.currency')
        purchase_report_line_obj = self.pool.get('marcos.dgii.purchase.report.line')

        domain_filters = []

        #if wizard.subsidiary_ids:
        #    domain_filters.append(('subsidiary_id', 'in', [
        #        subsidiary.id for subsidiary in wizard.subsidiary_ids]))


        #('subsidiary_id', 'in', [subsidiary.id for subsidiary in wizard.subsidiary_ids])
        draft_purchase_inv_ids = invoice_obj.search(cr, uid, [("state", "not in", ["open", "paid", "cancel"]),
                                                              ("period_id", "=", period_id),
                                                              ('reference_type', 'not in', ['not']),
                                                              ("type", "in", ["in_invoice", "in_refund"]),
                                                              ('subsidiary_id', 'in', [subsidiary.id for subsidiary in wizard.subsidiary_ids])])
        if draft_purchase_inv_ids:
            raise osv.except_osv(_(u'Compras o Notas de Crédito en Borrador!'), _(u"Asegúrese que todas sus compras y notas de crédito este validadas."))

        purchase_inv_ids = invoice_obj.search(cr, uid, [("state", "in", ["open", "paid"]),
                                                        ("period_id", "=", period_id),
                                                        ('reference_type', 'not in', ['not']),
                                                        ("type", "in", ["in_invoice", "in_refund"]),
                                                        ('subsidiary_id', 'in', [subsidiary.id for subsidiary in wizard.subsidiary_ids])])

        line = 1

        for inv_id in purchase_inv_ids:
            invoice = invoice_obj.browse(cr, uid, inv_id)
            if invoice.reference_type != "ext":
                payment_date = None
                if invoice.payment_ids and not invoice.residual:  # Invoice must be completly payed
                    payment_date = invoice.payment_ids[0].date.replace("-", "")

                if (not invoice.partner_id.ref or not len(invoice.partner_id.ref) in [9, 11]):
                    raise osv.except_osv(_(u'RNC/Cédula'), _(u"Verifique el RNC/Cédula de este proveedor: %s" % invoice.partner_id.name))

                ref_type = 1 if len(invoice.partner_id.ref) == 9 else 2

                tax_line_ids = tax_line_obj.search(cr, uid, [("invoice_id", "=", invoice.id)])

                company_currency = self.pool['res.company'].browse(cr, uid, invoice.company_id.id).currency_id.id
                MONTO_FACTURADO = cur_obj.compute(cr, uid, invoice.currency_id.id, company_currency, invoice.amount_untaxed, context={'date': invoice.date_invoice or time.strftime('%Y-%m-%d')}, round=False)

                ITBIS_PAGADO = 0.00
                ITBIS_RETENIDO = 0.00
                RETENCION_RENTA = 0.00
                for tax_line in tax_line_obj.browse(cr, uid, tax_line_ids):
                    #tax_ids = tax_obj.search(cr, uid, [("account_collected_id", "=", tax_line.account_id.id)])
                    tax_ids = tax_obj.search(cr, uid, [("base_code_id", "=", tax_line.base_code_id.id)])
                    if tax_ids:
                        tax = tax_obj.browse(cr, uid, tax_ids)[0]
                        if not tax.itbis and tax.retention:
                            if company_currency != invoice.currency_id.id: # TODO when invoice is differente currency lose presition on tax calculator
                                RETENCION_RENTA += MONTO_FACTURADO * tax.amount
                            else:
                                RETENCION_RENTA += tax_line.tax_amount
                        elif tax.itbis and not tax.retention:
                            if company_currency != invoice.currency_id.id: # TODO when invoice is differente currency lose presition on tax calculator
                                ITBIS_PAGADO += MONTO_FACTURADO * tax.amount
                            else:
                                ITBIS_PAGADO += tax_line.tax_amount
                        elif tax.itbis and tax.retention:
                            if not payment_date:
                                payment_date = invoice.date_invoice.replace(u"-", u"")
                            if company_currency != invoice.currency_id.id: # TODO when invoice is differente currency lose presition on tax calculator
                                ITBIS_RETENIDO += MONTO_FACTURADO * tax.amount
                            else:
                                ITBIS_RETENIDO += tax_line.tax_amount

                if invoice.reference_type == 'none':
                    raise osv.except_osv(_(u'Tipo de comprobante invalido!'), _(u"Verifique el tipo de este proveedor: %s" % invoice.number))

                if not invoice.number:
                    raise osv.except_osv(_(u'Error inesperado!'), _(u"Comuniquese con el aministrador para la factura de compra con el id: %s" % invoice.id))

                values = {
                    u'RNC_CEDULA': invoice.partner_id.ref,
                    u'TIPO_DE_IDENTIFICACION': ref_type,
                    u'TIPO_DE_BIENES_SERVICIOS_COMPRADOS': invoice.reference_type,
                    u'NUMERO_COMPROBANTE_FISCAL': invoice.number,
                    u'NUMERO_DE_COMPROBANTE_MODIFICADO': invoice.parent_id.number,
                    u'FECHA_COMPROBANTE': invoice.date_invoice.replace(u"-", u""),
                    u'FECHA_PAGO': payment_date,
                    u'ITBIS_PAGADO': abs(ITBIS_PAGADO),
                    u'ITBIS_RETENIDO': abs(ITBIS_RETENIDO),
                    u'MONTO_FACTURADO': abs(MONTO_FACTURADO),
                    u'RETENCION_RENTA': abs(RETENCION_RENTA),
                    u"line": line,
                    u'purchase_report_id': purchase_report_id
                    }

                line += 1
                purchase_report_line_obj.create(cr, uid, values, context=context)
        self.action_generate_606(cr, uid, purchase_report_id, context=context)
        return True



    def action_generate_606(self, cr, uid, ids, context=None):
        path = '/tmp/606.txt'
        f = open(path,'w')

        # Report Header
        header_obj = self.pool.get('marcos.dgii.purchase.report')
        header = header_obj.browse(cr, uid, ids, context=context)

        if not header.subsidiary_id.vat:
            raise osv.except_osv(_(u'Advertencia!'), _(u"Debe configurar el RNC de la empresa!"))

        document_header = header.subsidiary_id.vat.replace('-', '').rjust(11)
        period_month = header.period_id.name[:2]
        period_year = header.period_id.name[-4:]
        period = period_year + period_month
        count = str(header.line_count).zfill(12)
        total = ('%.2f' % header.billed_amount_total).zfill(16)
        isr = ('%.2f' % header.retained_isr_total).zfill(12)
        if int(header.period_id.name[-4:]) < 2015:
            header_str = '606' + document_header + period + count + total
        else:
            header_str = '606' + document_header + period + count + total + isr
        f.write(header_str + '\n')

        # Report Detail Lines
        for line in header.purchase_report_line_ids:
            document = line.RNC_CEDULA.replace('-', '').rjust(11)
            doc_type = str(line.TIPO_DE_IDENTIFICACION)
            line_type = line.TIPO_DE_BIENES_SERVICIOS_COMPRADOS
            ncf = line.NUMERO_COMPROBANTE_FISCAL.rjust(19)
            ref_ncf = line.NUMERO_DE_COMPROBANTE_MODIFICADO.rjust(19) if line.NUMERO_DE_COMPROBANTE_MODIFICADO else u''.rjust(19)  # when line is created manually it returns false instead of u''
            # dt = datetime.strptime(line.purchase_date, '%Y-%m-%d %H:%M:%S')
            purchase_date = line.FECHA_COMPROBANTE
            payment_date = line.FECHA_PAGO.rjust(8) if line.FECHA_PAGO else u''.rjust(8)  # when line is created manually it returns false instead of u''
            ITBIS_PAGADO = ('%.2f' % line.ITBIS_PAGADO).zfill(12)
            ITBIS_RETENIDO = ('%.2f' % line.ITBIS_RETENIDO).zfill(12)
            MONTO_FACTURADO = ('%.2f' % line.MONTO_FACTURADO).zfill(12)
            RETENCION_RENTA = ('%.2f' % line.RETENCION_RENTA).zfill(12)
            if int(header.period_id.name[-4:]) < 2015:
                line_str = document + doc_type + line_type + ncf + ref_ncf + purchase_date + payment_date + ITBIS_PAGADO + ITBIS_RETENIDO + MONTO_FACTURADO
            else:
                line_str = document + doc_type + line_type + ncf + ref_ncf + purchase_date + payment_date + ITBIS_PAGADO + ITBIS_RETENIDO + MONTO_FACTURADO+RETENCION_RENTA
            f.write(line_str+ '\n')

        f.close()

        f = open(path,'rb')
        report = base64.b64encode(f.read())
        f.close()
        report_name = 'DGII_F_606_' + document_header + '_' + period_year + period_month + '.TXT'
        self.write(cr, uid, [ids], {'report': report, 'report_name': report_name})
        return True


class purchase_report_line(osv.Model):
    """
    606 Purchase of Goods and Services report lines.

    """

    _name = 'marcos.dgii.purchase.report.line'
    _order = "line"

    _columns = {
        u"line": fields.integer(u"Linea"),
        u'RNC_CEDULA': fields.char(u"RNC/Cédula", 11, required=True),
        u'TIPO_DE_IDENTIFICACION': fields.selection([(1, u'RNC'), (2, u'Cédula')], size=1, string=u"Tipo de Documento", required=True),
        u'TIPO_DE_BIENES_SERVICIOS_COMPRADOS': fields.char(u"Tipo de Compra", 2, required=True),
        u'NUMERO_COMPROBANTE_FISCAL': fields.char(u'NCF', 19, required=True),
        u'NUMERO_DE_COMPROBANTE_MODIFICADO': fields.char(u"Afecta", 19, required=False),
        u'FECHA_COMPROBANTE': fields.char(u"Fecha", 8),
        u'FECHA_PAGO': fields.char(u'Pagado', 8),
        u'ITBIS_PAGADO': fields.float(u'ITBIS'),
        u'ITBIS_RETENIDO': fields.float(u'ITBIS Retenido'),
        u'MONTO_FACTURADO': fields.float(u'Facturado'),
        u'RETENCION_RENTA': fields.float(u'Retenciones del ISR'),
        u'purchase_report_id': fields.many2one('marcos.dgii.purchase.report', u"Reporte de Compras", required=True, ondelete="cascade")

        }

